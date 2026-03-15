package com.emulator.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import oshi.SystemInfo;
import oshi.hardware.*;
import oshi.software.os.OSProcess;
import oshi.software.os.OperatingSystem;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Pattern;

@Service
public class StatsCollectorService {

    private final ObjectMapper objectMapper;
    private final ConfigService configService;
    private final SystemInfo systemInfo = new SystemInfo();
    private final HardwareAbstractionLayer hardware = systemInfo.getHardware();
    private final OperatingSystem os = systemInfo.getOperatingSystem();
    private final CentralProcessor processor = hardware.getProcessor();

    // Collection state
    private ScheduledExecutorService scheduler;
    private final AtomicBoolean isCollecting = new AtomicBoolean(false);
    private String currentTestId;
    private String currentTestRunId;
    private String currentScenarioId;
    private String currentMode;
    private double collectIntervalSec;
    private Instant collectionStartTime;
    private final ConcurrentLinkedDeque<Map<String, Object>> samples = new ConcurrentLinkedDeque<>();

    // Previous tick values for CPU calculation (used only by background collector)
    private long[] prevTicks;
    // Last CPU reading from background collector (thread-safe for getSystemStats)
    private volatile double lastCpuPercent = 0.0;
    // Previous disk/network counters for rate calculation
    private long prevDiskRead, prevDiskWrite;
    private long prevNetSent, prevNetRecv;
    private Instant prevSampleTime;

    // Previous OSProcess snapshots for per-process CPU calculation (keyed by PID)
    private final ConcurrentHashMap<Integer, OSProcess> prevProcessSnapshots = new ConcurrentHashMap<>();

    // Iteration timing
    private final List<Double> iterationTimes = Collections.synchronizedList(new ArrayList<>());

    // Saved stats files mapping: testRunId -> filePath
    private final ConcurrentHashMap<String, String> savedStatsFiles = new ConcurrentHashMap<>();

    public StatsCollectorService(ObjectMapper objectMapper, ConfigService configService) {
        this.objectMapper = objectMapper;
        this.configService = configService;
        this.prevTicks = processor.getSystemCpuLoadTicks();
    }

    public void startCollection(String testId, String testRunId, String scenarioId,
                                String mode, double intervalSec) {
        if (isCollecting.get()) {
            stopCollection();
        }
        this.currentTestId = testId;
        this.currentTestRunId = testRunId;
        this.currentScenarioId = scenarioId;
        this.currentMode = mode;
        this.collectIntervalSec = intervalSec;
        this.collectionStartTime = Instant.now();
        this.samples.clear();

        // Initialize baseline counters
        prevTicks = processor.getSystemCpuLoadTicks();
        initDiskNetCounters();
        prevSampleTime = Instant.now();

        isCollecting.set(true);
        scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "stats-collector");
            t.setDaemon(true);
            return t;
        });
        long intervalMs = (long) (intervalSec * 1000);
        scheduler.scheduleAtFixedRate(this::collectSample, intervalMs, intervalMs, TimeUnit.MILLISECONDS);
    }

    public String stopCollection() {
        isCollecting.set(false);
        if (scheduler != null) {
            scheduler.shutdownNow();
            scheduler = null;
        }
        // Save to file
        return saveStatsToFile();
    }

    private void collectSample() {
        try {
            Instant now = Instant.now();
            double elapsed = (now.toEpochMilli() - collectionStartTime.toEpochMilli()) / 1000.0;
            double timeDelta = (now.toEpochMilli() - prevSampleTime.toEpochMilli()) / 1000.0;
            if (timeDelta <= 0) timeDelta = collectIntervalSec;

            // CPU — only the background collector uses prevTicks (no concurrent access)
            double cpuPercent = processor.getSystemCpuLoadBetweenTicks(prevTicks) * 100.0;
            prevTicks = processor.getSystemCpuLoadTicks();
            lastCpuPercent = cpuPercent;

            // Memory
            GlobalMemory mem = hardware.getMemory();
            long totalMem = mem.getTotal();
            long availMem = mem.getAvailable();
            long usedMem = totalMem - availMem;
            double memPercent = totalMem > 0 ? (usedMem * 100.0 / totalMem) : 0;
            double memUsedMb = usedMem / (1024.0 * 1024.0);
            double memAvailMb = availMem / (1024.0 * 1024.0);

            // Disk
            long diskRead = 0, diskWrite = 0;
            for (HWDiskStore disk : hardware.getDiskStores()) {
                disk.updateAttributes();
                diskRead += disk.getReadBytes();
                diskWrite += disk.getWriteBytes();
            }
            double diskReadRate = Math.max(0, (diskRead - prevDiskRead) / timeDelta / (1024.0 * 1024.0));
            double diskWriteRate = Math.max(0, (diskWrite - prevDiskWrite) / timeDelta / (1024.0 * 1024.0));
            prevDiskRead = diskRead;
            prevDiskWrite = diskWrite;

            // Network
            long netSent = 0, netRecv = 0;
            for (NetworkIF net : hardware.getNetworkIFs()) {
                net.updateAttributes();
                netSent += net.getBytesSent();
                netRecv += net.getBytesRecv();
            }
            double netSentRate = Math.max(0, (netSent - prevNetSent) / timeDelta / (1024.0 * 1024.0));
            double netRecvRate = Math.max(0, (netRecv - prevNetRecv) / timeDelta / (1024.0 * 1024.0));
            prevNetSent = netSent;
            prevNetRecv = netRecv;

            prevSampleTime = now;

            // Per-process stats
            List<Map<String, Object>> processStats = collectProcessStats();

            Map<String, Object> sample = new LinkedHashMap<>();
            sample.put("timestamp", formatTimestamp(now));
            sample.put("elapsed_sec", round2(elapsed));
            sample.put("cpu_percent", round1(cpuPercent));
            sample.put("memory_percent", round1(memPercent));
            sample.put("memory_used_mb", round1(memUsedMb));
            sample.put("memory_available_mb", round1(memAvailMb));
            sample.put("disk_read_bytes", diskRead);
            sample.put("disk_write_bytes", diskWrite);
            sample.put("disk_read_rate_mbps", round2(diskReadRate));
            sample.put("disk_write_rate_mbps", round2(diskWriteRate));
            sample.put("network_sent_bytes", netSent);
            sample.put("network_recv_bytes", netRecv);
            sample.put("network_sent_rate_mbps", round2(netSentRate));
            sample.put("network_recv_rate_mbps", round2(netRecvRate));
            sample.put("process_stats", processStats);

            samples.addLast(sample);

            // Trim if over limit
            int maxSamples = configService.getMaxMemorySamples();
            while (samples.size() > maxSamples) {
                samples.pollFirst();
            }
        } catch (Exception e) {
            // Don't let collection thread die
            e.printStackTrace();
        }
    }

    private List<Map<String, Object>> collectProcessStats() {
        List<Map<String, Object>> result = new ArrayList<>();
        List<String> patterns = configService.getServiceMonitorPatterns();
        if (patterns == null || patterns.isEmpty()) return result;

        List<Pattern> compiled = patterns.stream()
                .map(p -> Pattern.compile(p, Pattern.CASE_INSENSITIVE))
                .toList();

        Set<Integer> seenPids = new HashSet<>();
        for (OSProcess proc : os.getProcesses()) {
            String name = proc.getName();
            for (Pattern pat : compiled) {
                if (pat.matcher(name).find()) {
                    int pid = proc.getProcessID();
                    seenPids.add(pid);

                    // Use previous snapshot for CPU delta; first time will read 0%
                    OSProcess prev = prevProcessSnapshots.get(pid);
                    double cpuLoad = (prev != null)
                            ? proc.getProcessCpuLoadBetweenTicks(prev) * 100.0
                            : 0.0;
                    // Cache current snapshot for next interval
                    prevProcessSnapshots.put(pid, proc);

                    long totalMem = hardware.getMemory().getTotal();
                    long rss = proc.getResidentSetSize();

                    Map<String, Object> ps = new LinkedHashMap<>();
                    ps.put("name", name);
                    ps.put("pid", pid);
                    ps.put("cpu_percent", round1(cpuLoad));
                    ps.put("memory_percent", round1(totalMem > 0 ? rss * 100.0 / totalMem : 0));
                    ps.put("memory_rss_mb", round1(rss / (1024.0 * 1024.0)));
                    result.add(ps);
                    break;
                }
            }
        }
        // Clean up stale PIDs that no longer exist
        prevProcessSnapshots.keySet().retainAll(seenPids);
        return result;
    }

    public Map<String, Object> getSystemStats() {
        double cpuPercent;
        if (isCollecting.get()) {
            // Use last value from background collector to avoid racing on CentralProcessor
            cpuPercent = lastCpuPercent;
        } else {
            // No background collector — do a standalone measurement with dedicated ticks
            long[] standaloneTicks = processor.getSystemCpuLoadTicks();
            try { Thread.sleep(500); } catch (InterruptedException ignored) {}
            cpuPercent = processor.getSystemCpuLoadBetweenTicks(standaloneTicks) * 100.0;
        }

        GlobalMemory mem = hardware.getMemory();
        long totalMem = mem.getTotal();
        long availMem = mem.getAvailable();
        long usedMem = totalMem - availMem;

        long diskRead = 0, diskWrite = 0;
        for (HWDiskStore disk : hardware.getDiskStores()) {
            disk.updateAttributes();
            diskRead += disk.getReadBytes();
            diskWrite += disk.getWriteBytes();
        }

        long netSent = 0, netRecv = 0;
        for (NetworkIF net : hardware.getNetworkIFs()) {
            net.updateAttributes();
            netSent += net.getBytesSent();
            netRecv += net.getBytesRecv();
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("timestamp", formatTimestamp(Instant.now()));
        result.put("cpu_percent", round1(cpuPercent));
        result.put("memory_percent", round1(totalMem > 0 ? usedMem * 100.0 / totalMem : 0));
        result.put("memory_used_mb", round1(usedMem / (1024.0 * 1024.0)));
        result.put("memory_available_mb", round1(availMem / (1024.0 * 1024.0)));
        result.put("disk_read_bytes", diskRead);
        result.put("disk_write_bytes", diskWrite);
        result.put("network_sent_bytes", netSent);
        result.put("network_recv_bytes", netRecv);
        return result;
    }

    public Map<String, Object> getRecentStats(int count) {
        List<Map<String, Object>> recent = new ArrayList<>();
        Iterator<Map<String, Object>> it = samples.descendingIterator();
        while (it.hasNext() && recent.size() < count) {
            recent.add(0, it.next());
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("test_id", currentTestId);
        result.put("test_run_id", currentTestRunId);
        result.put("is_collecting", isCollecting.get());
        result.put("total_samples", samples.size());
        result.put("returned_samples", recent.size());
        result.put("samples", recent);
        return result;
    }

    public Map<String, Object> getAllStats(String testRunId) throws Exception {
        String filePath = savedStatsFiles.get(testRunId);
        if (filePath == null) {
            // Also check if currently collecting for this test_run_id
            if (isCollecting.get() && testRunId.equals(currentTestRunId)) {
                throw new IllegalStateException("Test is still running. Stop the test first.");
            }
            throw new java.io.FileNotFoundException("Stats file not found for test_run_id: " + testRunId);
        }
        String json = Files.readString(Path.of(filePath));
        return objectMapper.readValue(json, Map.class);
    }

    private String saveStatsToFile() {
        try {
            Instant endTime = Instant.now();
            double durationSec = (endTime.toEpochMilli() - collectionStartTime.toEpochMilli()) / 1000.0;

            List<Map<String, Object>> allSamples = new ArrayList<>(samples);

            Map<String, Object> metadata = new LinkedHashMap<>();
            metadata.put("test_id", currentTestId);
            metadata.put("test_run_id", currentTestRunId);
            metadata.put("scenario_id", currentScenarioId);
            metadata.put("mode", currentMode);
            metadata.put("started_at", formatTimestamp(collectionStartTime));
            metadata.put("ended_at", formatTimestamp(endTime));
            metadata.put("duration_sec", round1(durationSec));
            metadata.put("collect_interval_sec", collectIntervalSec);
            metadata.put("total_samples", allSamples.size());

            Map<String, Object> summary = computeSummary(allSamples);

            Map<String, Object> statsData = new LinkedHashMap<>();
            statsData.put("metadata", metadata);
            statsData.put("samples", allSamples);
            statsData.put("summary", summary);

            String outputDir = configService.getStatsOutputDir();
            Files.createDirectories(Paths.get(outputDir));
            String safeRunId = currentTestRunId != null ? currentTestRunId.replaceAll("[^a-zA-Z0-9_-]", "_") : "unknown";
            String safeScenario = currentScenarioId != null ? currentScenarioId.replaceAll("[^a-zA-Z0-9_-]", "_") : "test";
            String fileName = safeRunId + "_" + safeScenario + "_" + currentMode + "_stats.json";
            Path filePath = Paths.get(outputDir, fileName);
            objectMapper.writerWithDefaultPrettyPrinter().writeValue(filePath.toFile(), statsData);

            savedStatsFiles.put(currentTestRunId, filePath.toString());
            return filePath.toString();
        } catch (Exception e) {
            e.printStackTrace();
            return null;
        }
    }

    private Map<String, Object> computeSummary(List<Map<String, Object>> samples) {
        Map<String, Object> summary = new LinkedHashMap<>();
        String[] metrics = {"cpu_percent", "memory_percent", "disk_read_rate_mbps",
                "disk_write_rate_mbps", "network_sent_rate_mbps", "network_recv_rate_mbps"};

        for (String metric : metrics) {
            List<Double> values = new ArrayList<>();
            for (Map<String, Object> s : samples) {
                Object v = s.get(metric);
                if (v instanceof Number) values.add(((Number) v).doubleValue());
            }
            summary.put(metric, computePercentiles(values));
        }
        // Per-process summary: aggregate by process name across all samples
        Map<String, Map<String, List<Double>>> procData = new LinkedHashMap<>();
        for (Map<String, Object> s : samples) {
            Object psObj = s.get("process_stats");
            if (psObj instanceof List) {
                for (Object item : (List<?>) psObj) {
                    if (item instanceof Map) {
                        @SuppressWarnings("unchecked")
                        Map<String, Object> ps = (Map<String, Object>) item;
                        String pname = String.valueOf(ps.get("name"));
                        procData.computeIfAbsent(pname, k -> {
                            Map<String, List<Double>> m = new LinkedHashMap<>();
                            m.put("cpu", new ArrayList<>());
                            m.put("mem", new ArrayList<>());
                            m.put("rss", new ArrayList<>());
                            return m;
                        });
                        Map<String, List<Double>> pd = procData.get(pname);
                        if (ps.get("cpu_percent") instanceof Number n) pd.get("cpu").add(n.doubleValue());
                        if (ps.get("memory_percent") instanceof Number n) pd.get("mem").add(n.doubleValue());
                        if (ps.get("memory_rss_mb") instanceof Number n) pd.get("rss").add(n.doubleValue());
                    }
                }
            }
        }
        Map<String, Object> processSummary = new LinkedHashMap<>();
        for (var entry : procData.entrySet()) {
            Map<String, Object> perProc = new LinkedHashMap<>();
            for (var mEntry : entry.getValue().entrySet()) {
                perProc.put(mEntry.getKey(), computePercentiles(mEntry.getValue()));
            }
            processSummary.put(entry.getKey(), perProc);
        }
        summary.put("process_stats", processSummary);
        return summary;
    }

    private Map<String, Object> computePercentiles(List<Double> values) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (values.isEmpty()) {
            result.put("avg", 0.0); result.put("min", 0.0); result.put("max", 0.0);
            result.put("p50", 0.0); result.put("p90", 0.0); result.put("p95", 0.0); result.put("p99", 0.0);
            return result;
        }
        Collections.sort(values);
        double sum = values.stream().mapToDouble(Double::doubleValue).sum();
        result.put("avg", round1(sum / values.size()));
        result.put("min", round1(values.get(0)));
        result.put("max", round1(values.get(values.size() - 1)));
        result.put("p50", round1(percentile(values, 50)));
        result.put("p90", round1(percentile(values, 90)));
        result.put("p95", round1(percentile(values, 95)));
        result.put("p99", round1(percentile(values, 99)));
        return result;
    }

    private double percentile(List<Double> sorted, double pct) {
        double k = (sorted.size() - 1) * pct / 100.0;
        int lower = (int) Math.floor(k);
        int upper = Math.min(lower + 1, sorted.size() - 1);
        double frac = k - lower;
        return sorted.get(lower) + frac * (sorted.get(upper) - sorted.get(lower));
    }

    // Iteration timing
    public void recordIteration(double durationMs) {
        iterationTimes.add(durationMs);
    }

    public Map<String, Object> getIterationTiming() {
        List<Double> times;
        synchronized (iterationTimes) {
            times = new ArrayList<>(iterationTimes);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        if (times.isEmpty()) {
            result.put("sample_count", 0);
            result.put("avg_ms", 0.0); result.put("stddev_ms", 0.0);
            result.put("min_ms", 0.0); result.put("max_ms", 0.0);
            result.put("p50_ms", 0.0); result.put("p90_ms", 0.0); result.put("p99_ms", 0.0);
            return result;
        }
        Collections.sort(times);
        double sum = times.stream().mapToDouble(Double::doubleValue).sum();
        double avg = sum / times.size();
        double variance = times.stream().mapToDouble(t -> (t - avg) * (t - avg)).sum() / times.size();

        result.put("sample_count", times.size());
        result.put("avg_ms", round1(avg));
        result.put("stddev_ms", round1(Math.sqrt(variance)));
        result.put("min_ms", round1(times.get(0)));
        result.put("max_ms", round1(times.get(times.size() - 1)));
        result.put("p50_ms", round1(percentile(times, 50)));
        result.put("p90_ms", round1(percentile(times, 90)));
        result.put("p99_ms", round1(percentile(times, 99)));
        return result;
    }

    public Map<String, Object> clearIterationTimes() {
        int prev;
        synchronized (iterationTimes) {
            prev = iterationTimes.size();
            iterationTimes.clear();
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("success", true);
        result.put("message", "Iteration stats cleared");
        return result;
    }

    // Accessors
    public boolean isCollecting() { return isCollecting.get(); }
    public String getCurrentTestId() { return currentTestId; }
    public String getCurrentTestRunId() { return currentTestRunId; }
    public int getSamplesCollected() { return samples.size(); }
    public double getCollectIntervalSec() { return collectIntervalSec; }

    private void initDiskNetCounters() {
        prevDiskRead = 0; prevDiskWrite = 0;
        for (HWDiskStore disk : hardware.getDiskStores()) {
            prevDiskRead += disk.getReadBytes();
            prevDiskWrite += disk.getWriteBytes();
        }
        prevNetSent = 0; prevNetRecv = 0;
        for (NetworkIF net : hardware.getNetworkIFs()) {
            prevNetSent += net.getBytesSent();
            prevNetRecv += net.getBytesRecv();
        }
    }

    private String formatTimestamp(Instant instant) {
        return DateTimeFormatter.ISO_INSTANT.format(instant);
    }

    private double round1(double v) { return Math.round(v * 10.0) / 10.0; }
    private double round2(double v) { return Math.round(v * 100.0) / 100.0; }
}
