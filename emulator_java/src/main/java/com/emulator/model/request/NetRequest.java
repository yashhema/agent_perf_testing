package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class NetRequest {
    @JsonProperty("duration_ms")
    private int durationMs;
    @JsonProperty("target_host")
    private String targetHost;
    @JsonProperty("target_port")
    private Integer targetPort;
    @JsonProperty("packet_size_bytes")
    private int packetSizeBytes = 1024;
    private String mode = "both";

    public int getDurationMs() { return durationMs; }
    public void setDurationMs(int v) { this.durationMs = v; }
    public String getTargetHost() { return targetHost; }
    public void setTargetHost(String v) { this.targetHost = v; }
    public Integer getTargetPort() { return targetPort; }
    public void setTargetPort(Integer v) { this.targetPort = v; }
    public int getPacketSizeBytes() { return packetSizeBytes; }
    public void setPacketSizeBytes(int v) { this.packetSizeBytes = v; }
    public String getMode() { return mode; }
    public void setMode(String v) { this.mode = v; }
}
