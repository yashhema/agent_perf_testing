package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class DiskRequest {
    @JsonProperty("duration_ms")
    private int durationMs;
    private String mode;
    @JsonProperty("size_mb")
    private int sizeMb = 100;
    @JsonProperty("block_size_kb")
    private int blockSizeKb = 64;

    public int getDurationMs() { return durationMs; }
    public void setDurationMs(int v) { this.durationMs = v; }
    public String getMode() { return mode; }
    public void setMode(String v) { this.mode = v; }
    public int getSizeMb() { return sizeMb; }
    public void setSizeMb(int v) { this.sizeMb = v; }
    public int getBlockSizeKb() { return blockSizeKb; }
    public void setBlockSizeKb(int v) { this.blockSizeKb = v; }
}
