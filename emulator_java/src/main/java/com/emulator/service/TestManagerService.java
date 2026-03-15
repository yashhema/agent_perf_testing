package com.emulator.service;

import com.emulator.model.request.StartTestRequest;
import com.emulator.model.response.TestStatusResponse;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;

@Service
public class TestManagerService {

    private final StatsCollectorService statsCollector;
    private final ConcurrentHashMap<String, TestState> tests = new ConcurrentHashMap<>();

    public TestManagerService(StatsCollectorService statsCollector) {
        this.statsCollector = statsCollector;
    }

    public TestStatusResponse startTest(StartTestRequest req) {
        String testId = "test-" + UUID.randomUUID().toString().substring(0, 8);
        Instant startedAt = Instant.now();

        TestState state = new TestState();
        state.testId = testId;
        state.testRunId = req.getTestRunId();
        state.scenarioId = req.getScenarioId();
        state.mode = req.getMode();
        state.status = "running";
        state.threadCount = req.getThreadCount();
        state.startedAt = startedAt;
        state.collectIntervalSec = req.getCollectIntervalSec();

        tests.put(testId, state);

        // Start stats collection
        statsCollector.startCollection(testId, req.getTestRunId(), req.getScenarioId(),
                req.getMode(), req.getCollectIntervalSec());

        return buildResponse(state);
    }

    public List<TestStatusResponse> listTests() {
        List<TestStatusResponse> result = new ArrayList<>();
        for (TestState state : tests.values()) {
            result.add(buildResponse(state));
        }
        return result;
    }

    public TestStatusResponse getTest(String testId) {
        TestState state = tests.get(testId);
        if (state == null) return null;
        return buildResponse(state);
    }

    public Map<String, Object> stopTest(String testId, boolean force) {
        TestState state = tests.get(testId);
        if (state == null) return null;

        state.status = "completed";
        String statsFile = statsCollector.stopCollection();
        int totalSamples = statsCollector.getSamplesCollected();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("success", true);
        result.put("message", "Test stopped and stats saved");
        result.put("stats_file", statsFile);
        result.put("total_samples", totalSamples);
        return result;
    }

    private TestStatusResponse buildResponse(TestState state) {
        TestStatusResponse resp = new TestStatusResponse();
        resp.setTestId(state.testId);
        resp.setTestRunId(state.testRunId);
        resp.setScenarioId(state.scenarioId);
        resp.setMode(state.mode);
        resp.setStatus(state.status);
        resp.setThreadCount(state.threadCount);
        resp.setIterationsCompleted(state.iterationsCompleted);
        resp.setStartedAt(formatTimestamp(state.startedAt));
        double elapsed = (Instant.now().toEpochMilli() - state.startedAt.toEpochMilli()) / 1000.0;
        resp.setElapsedSec(Math.round(elapsed * 10.0) / 10.0);
        resp.setErrorCount(state.errorCount);

        TestStatusResponse.StatsCollectionInfo sci = new TestStatusResponse.StatsCollectionInfo(
                statsCollector.isCollecting(),
                state.collectIntervalSec,
                statsCollector.getSamplesCollected()
        );
        resp.setStatsCollection(sci);
        return resp;
    }

    private String formatTimestamp(Instant instant) {
        return DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss")
                .withZone(ZoneOffset.UTC).format(instant);
    }

    private static class TestState {
        String testId;
        String testRunId;
        String scenarioId;
        String mode;
        String status;
        int threadCount;
        Instant startedAt;
        double collectIntervalSec;
        long iterationsCompleted;
        long errorCount;
    }
}
