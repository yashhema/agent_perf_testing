package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class AgentServiceRequest {
    @JsonProperty("agent_type")
    private String agentType;
    private String action;

    public String getAgentType() { return agentType; }
    public void setAgentType(String v) { this.agentType = v; }
    public String getAction() { return action; }
    public void setAction(String v) { this.action = v; }
}
