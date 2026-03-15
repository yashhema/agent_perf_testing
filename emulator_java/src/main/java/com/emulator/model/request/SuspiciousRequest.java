package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class SuspiciousRequest {
    @JsonProperty("activity_type")
    private String activityType;
    @JsonProperty("duration_ms")
    private int durationMs = 500;

    public String getActivityType() { return activityType; }
    public void setActivityType(String v) { this.activityType = v; }
    public int getDurationMs() { return durationMs; }
    public void setDurationMs(int v) { this.durationMs = v; }
}
