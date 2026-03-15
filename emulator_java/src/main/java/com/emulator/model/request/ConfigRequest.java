package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

public class ConfigRequest {
    @JsonProperty("output_folders")
    private List<String> outputFolders;
    private PartnerRequest partner;
    private StatsConfigRequest stats;

    public List<String> getOutputFolders() { return outputFolders; }
    public void setOutputFolders(List<String> outputFolders) { this.outputFolders = outputFolders; }
    public PartnerRequest getPartner() { return partner; }
    public void setPartner(PartnerRequest partner) { this.partner = partner; }
    public StatsConfigRequest getStats() { return stats; }
    public void setStats(StatsConfigRequest stats) { this.stats = stats; }

    public static class PartnerRequest {
        private String fqdn;
        private int port = 8080;

        public String getFqdn() { return fqdn; }
        public void setFqdn(String fqdn) { this.fqdn = fqdn; }
        public int getPort() { return port; }
        public void setPort(int port) { this.port = port; }
    }

    public static class StatsConfigRequest {
        @JsonProperty("output_dir")
        private String outputDir = "./stats";
        @JsonProperty("default_interval_sec")
        private double defaultIntervalSec = 1.0;
        @JsonProperty("max_memory_samples")
        private int maxMemorySamples = 10000;
        @JsonProperty("service_monitor_patterns")
        private List<String> serviceMonitorPatterns = List.of();

        public String getOutputDir() { return outputDir; }
        public void setOutputDir(String outputDir) { this.outputDir = outputDir; }
        public double getDefaultIntervalSec() { return defaultIntervalSec; }
        public void setDefaultIntervalSec(double v) { this.defaultIntervalSec = v; }
        public int getMaxMemorySamples() { return maxMemorySamples; }
        public void setMaxMemorySamples(int v) { this.maxMemorySamples = v; }
        public List<String> getServiceMonitorPatterns() { return serviceMonitorPatterns; }
        public void setServiceMonitorPatterns(List<String> v) { this.serviceMonitorPatterns = v; }
    }
}
