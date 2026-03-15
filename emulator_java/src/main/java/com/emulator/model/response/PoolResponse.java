package com.emulator.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;

public class PoolResponse {
    private boolean allocated;
    @JsonProperty("size_bytes")
    private long sizeBytes;

    public PoolResponse() {}
    public PoolResponse(boolean allocated, long sizeBytes) {
        this.allocated = allocated;
        this.sizeBytes = sizeBytes;
    }

    public boolean isAllocated() { return allocated; }
    public void setAllocated(boolean v) { this.allocated = v; }
    public long getSizeBytes() { return sizeBytes; }
    public void setSizeBytes(long v) { this.sizeBytes = v; }
}
