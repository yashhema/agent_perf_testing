package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.Map;

public class AgentInstallRequest {
    @JsonProperty("agent_type")
    private String agentType;
    @JsonProperty("installer_path")
    private String installerPath;
    @JsonProperty("install_options")
    private Map<String, Object> installOptions = Map.of();

    public String getAgentType() { return agentType; }
    public void setAgentType(String v) { this.agentType = v; }
    public String getInstallerPath() { return installerPath; }
    public void setInstallerPath(String v) { this.installerPath = v; }
    public Map<String, Object> getInstallOptions() { return installOptions; }
    public void setInstallOptions(Map<String, Object> v) { this.installOptions = v; }
}
