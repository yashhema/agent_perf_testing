package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class MemRequest {
    @JsonProperty("duration_ms")
    private int durationMs;
    @JsonProperty("size_mb")
    private int sizeMb;
    private String pattern = "sequential";

    public int getDurationMs() { return durationMs; }
    public void setDurationMs(int v) { this.durationMs = v; }
    public int getSizeMb() { return sizeMb; }
    public void setSizeMb(int v) { this.sizeMb = v; }
    public String getPattern() { return pattern; }
    public void setPattern(String v) { this.pattern = v; }
}
