package com.emulator.model.response;

import com.fasterxml.jackson.annotation.JsonProperty;

public class FileOperationResult {
    private String operation = "FILE";
    private String status;
    @JsonProperty("duration_ms")
    private long durationMs;
    @JsonProperty("size_bracket")
    private String sizeBracket;
    @JsonProperty("actual_size_bytes")
    private long actualSizeBytes;
    @JsonProperty("output_format")
    private String outputFormat;
    @JsonProperty("output_folder")
    private String outputFolder;
    @JsonProperty("output_file")
    private String outputFile;
    @JsonProperty("is_confidential")
    private boolean isConfidential;
    @JsonProperty("is_zipped")
    private boolean isZipped;
    @JsonProperty("source_files_used")
    private int sourceFilesUsed;
    @JsonProperty("error_message")
    private String errorMessage;

    public String getOperation() { return operation; }
    public void setOperation(String v) { this.operation = v; }
    public String getStatus() { return status; }
    public void setStatus(String v) { this.status = v; }
    public long getDurationMs() { return durationMs; }
    public void setDurationMs(long v) { this.durationMs = v; }
    public String getSizeBracket() { return sizeBracket; }
    public void setSizeBracket(String v) { this.sizeBracket = v; }
    public long getActualSizeBytes() { return actualSizeBytes; }
    public void setActualSizeBytes(long v) { this.actualSizeBytes = v; }
    public String getOutputFormat() { return outputFormat; }
    public void setOutputFormat(String v) { this.outputFormat = v; }
    public String getOutputFolder() { return outputFolder; }
    public void setOutputFolder(String v) { this.outputFolder = v; }
    public String getOutputFile() { return outputFile; }
    public void setOutputFile(String v) { this.outputFile = v; }
    public boolean isConfidential() { return isConfidential; }
    public void setConfidential(boolean v) { this.isConfidential = v; }
    public boolean isZipped() { return isZipped; }
    public void setZipped(boolean v) { this.isZipped = v; }
    public int getSourceFilesUsed() { return sourceFilesUsed; }
    public void setSourceFilesUsed(int v) { this.sourceFilesUsed = v; }
    public String getErrorMessage() { return errorMessage; }
    public void setErrorMessage(String v) { this.errorMessage = v; }
}
