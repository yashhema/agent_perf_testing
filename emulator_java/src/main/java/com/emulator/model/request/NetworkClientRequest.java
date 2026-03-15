package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class NetworkClientRequest {
    @JsonProperty("req_size_kb")
    private int reqSizeKb = 100;
    @JsonProperty("resp_size_kb")
    private int respSizeKb = 50;

    public int getReqSizeKb() { return reqSizeKb; }
    public void setReqSizeKb(int v) { this.reqSizeKb = v; }
    public int getRespSizeKb() { return respSizeKb; }
    public void setRespSizeKb(int v) { this.respSizeKb = v; }
}
