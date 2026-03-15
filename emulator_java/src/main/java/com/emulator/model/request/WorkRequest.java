package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class WorkRequest {
    @JsonProperty("cpu_ms")
    private int cpuMs = 10;
    private double intensity = 0.8;
    @JsonProperty("touch_mb")
    private double touchMb = 1.0;
    @JsonProperty("touch_pattern")
    private String touchPattern = "random";

    public int getCpuMs() { return cpuMs; }
    public void setCpuMs(int v) { this.cpuMs = v; }
    public double getIntensity() { return intensity; }
    public void setIntensity(double v) { this.intensity = v; }
    public double getTouchMb() { return touchMb; }
    public void setTouchMb(double v) { this.touchMb = v; }
    public String getTouchPattern() { return touchPattern; }
    public void setTouchPattern(String v) { this.touchPattern = v; }
}
