package com.emulator.model.request;

import com.fasterxml.jackson.annotation.JsonProperty;

public class FileOperationRequest {
    @JsonProperty("is_confidential")
    private boolean isConfidential = false;
    @JsonProperty("make_zip")
    private boolean makeZip = false;
    @JsonProperty("size_bracket")
    private String sizeBracket;
    @JsonProperty("target_size_kb")
    private Integer targetSizeKb;
    @JsonProperty("output_format")
    private String outputFormat;
    @JsonProperty("output_folder_idx")
    private Integer outputFolderIdx;
    @JsonProperty("source_file_ids")
    private String sourceFileIds;

    public boolean isConfidential() { return isConfidential; }
    public void setConfidential(boolean v) { this.isConfidential = v; }
    public boolean isMakeZip() { return makeZip; }
    public void setMakeZip(boolean v) { this.makeZip = v; }
    public String getSizeBracket() { return sizeBracket; }
    public void setSizeBracket(String v) { this.sizeBracket = v; }
    public Integer getTargetSizeKb() { return targetSizeKb; }
    public void setTargetSizeKb(Integer v) { this.targetSizeKb = v; }
    public String getOutputFormat() { return outputFormat; }
    public void setOutputFormat(String v) { this.outputFormat = v; }
    public Integer getOutputFolderIdx() { return outputFolderIdx; }
    public void setOutputFolderIdx(Integer v) { this.outputFolderIdx = v; }
    public String getSourceFileIds() { return sourceFileIds; }
    public void setSourceFileIds(String v) { this.sourceFileIds = v; }
}
