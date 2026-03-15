package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class PoolRequest {
    @JsonProperty("size_gb")
    private Double sizeGb;

    @JsonProperty("heap_percent")
    private Double heapPercent;

    public Double getSizeGb() { return sizeGb; }
    public void setSizeGb(Double sizeGb) { this.sizeGb = sizeGb; }
    public Double getHeapPercent() { return heapPercent; }
    public void setHeapPercent(Double heapPercent) { this.heapPercent = heapPercent; }
}
