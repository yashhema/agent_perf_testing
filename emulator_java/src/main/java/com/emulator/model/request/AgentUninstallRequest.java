package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AgentUninstallRequest {
    @JsonProperty("agent_type")
    private String agentType;
    private boolean force = false;

    public String getAgentType() { return agentType; }
    public void setAgentType(String v) { this.agentType = v; }
    public boolean isForce() { return force; }
    public void setForce(boolean v) { this.force = v; }
}
