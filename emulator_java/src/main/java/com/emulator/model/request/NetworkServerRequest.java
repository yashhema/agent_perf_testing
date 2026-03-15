package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class NetworkServerRequest {
    private byte[] payload;
    @JsonProperty("resp_size_kb")
    private int respSizeKb = 50;

    public byte[] getPayload() { return payload; }
    public void setPayload(byte[] v) { this.payload = v; }
    public int getRespSizeKb() { return respSizeKb; }
    public void setRespSizeKb(int v) { this.respSizeKb = v; }
}
