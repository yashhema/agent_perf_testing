package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class StartTestRequest {
    @JsonProperty("test_run_id")
    private String testRunId;
    @JsonProperty("scenario_id")
    private String scenarioId;
    private String mode = "normal";
    @JsonProperty("collect_interval_sec")
    private double collectIntervalSec = 1.0;
    @JsonProperty("thread_count")
    private int threadCount = 1;
    @JsonProperty("duration_sec")
    private Integer durationSec;
    @JsonProperty("loop_count")
    private Integer loopCount;
    private CompositeOperationRequest operation;

    public String getTestRunId() { return testRunId; }
    public void setTestRunId(String v) { this.testRunId = v; }
    public String getScenarioId() { return scenarioId; }
    public void setScenarioId(String v) { this.scenarioId = v; }
    public String getMode() { return mode; }
    public void setMode(String v) { this.mode = v; }
    public double getCollectIntervalSec() { return collectIntervalSec; }
    public void setCollectIntervalSec(double v) { this.collectIntervalSec = v; }
    public int getThreadCount() { return threadCount; }
    public void setThreadCount(int v) { this.threadCount = v; }
    public Integer getDurationSec() { return durationSec; }
    public void setDurationSec(Integer v) { this.durationSec = v; }
    public Integer getLoopCount() { return loopCount; }
    public void setLoopCount(Integer v) { this.loopCount = v; }
    public CompositeOperationRequest getOperation() { return operation; }
    public void setOperation(CompositeOperationRequest v) { this.operation = v; }

    public static class CompositeOperationRequest {
        private CpuRequest cpu;
        private MemRequest mem;
        private DiskRequest disk;
        private NetRequest net;
        private boolean parallel = true;

        public CpuRequest getCpu() { return cpu; }
        public void setCpu(CpuRequest v) { this.cpu = v; }
        public MemRequest getMem() { return mem; }
        public void setMem(MemRequest v) { this.mem = v; }
        public DiskRequest getDisk() { return disk; }
        public void setDisk(DiskRequest v) { this.disk = v; }
        public NetRequest getNet() { return net; }
        public void setNet(NetRequest v) { this.net = v; }
        public boolean isParallel() { return parallel; }
        public void setParallel(boolean v) { this.parallel = v; }
    }
}
