package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class CpuRequest {
    @JsonProperty("duration_ms")
    private int durationMs;
    private double intensity = 1.0;

    public int getDurationMs() { return durationMs; }
    public void setDurationMs(int durationMs) { this.durationMs = durationMs; }
    public double getIntensity() { return intensity; }
    public void setIntensity(double intensity) { this.intensity = intensity; }
}
