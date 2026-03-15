package com.emulator.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;

public class TestStatusResponse {
    @JsonProperty("test_id")
    private String testId;
    @JsonProperty("test_run_id")
    private String testRunId;
    @JsonProperty("scenario_id")
    private String scenarioId;
    private String mode;
    private String status;
    @JsonProperty("thread_count")
    private int threadCount;
    @JsonProperty("iterations_completed")
    private long iterationsCompleted;
    @JsonProperty("started_at")
    private String startedAt;
    @JsonProperty("elapsed_sec")
    private double elapsedSec;
    @JsonProperty("error_count")
    private long errorCount;
    @JsonProperty("stats_collection")
    private StatsCollectionInfo statsCollection;

    public static class StatsCollectionInfo {
        private boolean enabled;
        @JsonProperty("interval_sec")
        private double intervalSec;
        @JsonProperty("samples_collected")
        private long samplesCollected;

        public StatsCollectionInfo() {}
        public StatsCollectionInfo(boolean enabled, double intervalSec, long samplesCollected) {
            this.enabled = enabled;
            this.intervalSec = intervalSec;
            this.samplesCollected = samplesCollected;
        }

        public boolean isEnabled() { return enabled; }
        public void setEnabled(boolean v) { this.enabled = v; }
        public double getIntervalSec() { return intervalSec; }
        public void setIntervalSec(double v) { this.intervalSec = v; }
        public long getSamplesCollected() { return samplesCollected; }
        public void setSamplesCollected(long v) { this.samplesCollected = v; }
    }

    public String getTestId() { return testId; }
    public void setTestId(String v) { this.testId = v; }
    public String getTestRunId() { return testRunId; }
    public void setTestRunId(String v) { this.testRunId = v; }
    public String getScenarioId() { return scenarioId; }
    public void setScenarioId(String v) { this.scenarioId = v; }
    public String getMode() { return mode; }
    public void setMode(String v) { this.mode = v; }
    public String getStatus() { return status; }
    public void setStatus(String v) { this.status = v; }
    public int getThreadCount() { return threadCount; }
    public void setThreadCount(int v) { this.threadCount = v; }
    public long getIterationsCompleted() { return iterationsCompleted; }
    public void setIterationsCompleted(long v) { this.iterationsCompleted = v; }
    public String getStartedAt() { return startedAt; }
    public void setStartedAt(String v) { this.startedAt = v; }
    public double getElapsedSec() { return elapsedSec; }
    public void setElapsedSec(double v) { this.elapsedSec = v; }
    public long getErrorCount() { return errorCount; }
    public void setErrorCount(long v) { this.errorCount = v; }
    public StatsCollectionInfo getStatsCollection() { return statsCollection; }
    public void setStatsCollection(StatsCollectionInfo v) { this.statsCollection = v; }
}
