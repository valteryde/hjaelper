(() => {
    "use strict";

    // DOM elements
    const pdfInput = document.getElementById("pdf-file");
    const apiKeyInput = document.getElementById("api-key");
    const providerSelect = document.getElementById("provider");
    const modelInput = document.getElementById("model");
    const chunkSizeInput = document.getElementById("chunk-size");
    const languageInput = document.getElementById("language");
    const skillLevelInput = document.getElementById("skill-level");
    const customPromptInput = document.getElementById("custom-prompt");
    const submitBtn = document.getElementById("submit-btn");

    // Analysis pass toggles
    const enableThreadInput = document.getElementById("enable-thread");
    const enableCoherenceInput = document.getElementById("enable-coherence");
    const enableFactcheckInput = document.getElementById("enable-factcheck");

    const uploadSection = document.getElementById("upload-section");
    const progressSection = document.getElementById("progress-section");
    const statusText = document.getElementById("status-text");
    const progressFill = document.getElementById("progress-fill");
    const progressDetail = document.getElementById("progress-detail");

    const downloadSection = document.getElementById("download-section");
    const downloadLink = document.getElementById("download-link");

    const errorSection = document.getElementById("error-section");
    const errorText = document.getElementById("error-text");

    // Restore saved values from localStorage
    const savedKey = localStorage.getItem("hjaelper_api_key");
    if (savedKey) apiKeyInput.value = savedKey;

    const savedProvider = localStorage.getItem("hjaelper_provider");
    if (savedProvider) providerSelect.value = savedProvider;

    const savedModel = localStorage.getItem("hjaelper_model");
    if (savedModel) modelInput.value = savedModel;

    const savedChunkSize = localStorage.getItem("hjaelper_chunk_size");
    if (savedChunkSize) chunkSizeInput.value = savedChunkSize;

    const savedLanguage = localStorage.getItem("hjaelper_language");
    if (savedLanguage) languageInput.value = savedLanguage;

    const savedSkillLevel = localStorage.getItem("hjaelper_skill_level");
    if (savedSkillLevel) skillLevelInput.value = savedSkillLevel;

    const savedCustomPrompt = localStorage.getItem("hjaelper_custom_prompt");
    if (savedCustomPrompt) customPromptInput.value = savedCustomPrompt;

    // Restore toggle states
    const savedThread = localStorage.getItem("hjaelper_enable_thread");
    if (savedThread === "true") enableThreadInput.checked = true;

    const savedCoherence = localStorage.getItem("hjaelper_enable_coherence");
    if (savedCoherence === "true") enableCoherenceInput.checked = true;

    const savedFactcheck = localStorage.getItem("hjaelper_enable_factcheck");
    if (savedFactcheck === "true") enableFactcheckInput.checked = true;

    // Upload handler
    submitBtn.addEventListener("click", async () => {
        const file = pdfInput.files[0];
        const apiKey = apiKeyInput.value.trim();
        const provider = providerSelect.value;
        const model = modelInput.value.trim();
        const chunkSize = chunkSizeInput.value;
        const language = languageInput.value.trim();
        const skillLevel = skillLevelInput.value.trim();
        const customPrompt = customPromptInput.value.trim();
        const enableThread = enableThreadInput.checked;
        const enableCoherence = enableCoherenceInput.checked;
        const enableFactcheck = enableFactcheckInput.checked;

        if (!file) return showError("Please select a PDF file.");
        if (!apiKey) return showError("Please enter your API key.");
        if (!model) return showError("Please enter a model name.");

        // Save to localStorage
        localStorage.setItem("hjaelper_api_key", apiKey);
        localStorage.setItem("hjaelper_provider", provider);
        localStorage.setItem("hjaelper_model", model);
        localStorage.setItem("hjaelper_chunk_size", chunkSize);
        localStorage.setItem("hjaelper_language", language);
        localStorage.setItem("hjaelper_skill_level", skillLevel);
        localStorage.setItem("hjaelper_custom_prompt", customPrompt);
        localStorage.setItem("hjaelper_enable_thread", enableThread);
        localStorage.setItem("hjaelper_enable_coherence", enableCoherence);
        localStorage.setItem("hjaelper_enable_factcheck", enableFactcheck);

        // Build FormData
        const formData = new FormData();
        formData.append("pdf", file);
        formData.append("api_key", apiKey);
        formData.append("provider", provider);
        formData.append("model", model);
        formData.append("chunk_size", chunkSize);
        formData.append("language", language);
        formData.append("skill_level", skillLevel);
        formData.append("custom_prompt", customPrompt);
        formData.append("enable_thread", enableThread);
        formData.append("enable_coherence", enableCoherence);
        formData.append("enable_factcheck", enableFactcheck);

        submitBtn.disabled = true;
        hideError();

        try {
            const res = await fetch("/api/upload/", {
                method: "POST",
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                showError(data.error || "Upload failed.");
                submitBtn.disabled = false;
                return;
            }

            // Switch to progress view
            uploadSection.hidden = true;
            progressSection.hidden = false;
            downloadSection.hidden = true;

            pollStatus(data.job_id);

        } catch (err) {
            showError("Network error: " + err.message);
            submitBtn.disabled = false;
        }
    });

    // Poll job status every 2 seconds
    function pollStatus(jobId) {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`/api/status/${jobId}/`);
                const data = await res.json();

                if (data.status === "processing" || data.status === "pending") {
                    statusText.textContent =
                        data.status === "pending" ? "Waiting to start..." : "Processing...";

                    if (data.total_chunks > 0) {
                        const pct = Math.round(
                            (data.completed_chunks / data.total_chunks) * 100
                        );
                        progressFill.style.width = pct + "%";
                        progressDetail.textContent =
                            `${data.completed_chunks} / ${data.total_chunks} chunks`;
                    }
                } else if (data.status === "done") {
                    clearInterval(interval);
                    progressSection.hidden = true;
                    downloadSection.hidden = false;
                    downloadLink.href = `/api/download/${jobId}/`;
                } else if (data.status === "error") {
                    clearInterval(interval);
                    progressSection.hidden = true;
                    showError(data.error_message || "An unknown error occurred.");
                    resetUpload();
                }
            } catch (err) {
                clearInterval(interval);
                showError("Lost connection to server.");
                resetUpload();
            }
        }, 2000);
    }

    function showError(msg) {
        errorSection.hidden = false;
        errorText.textContent = msg;
    }

    function hideError() {
        errorSection.hidden = true;
        errorText.textContent = "";
    }

    function resetUpload() {
        uploadSection.hidden = false;
        submitBtn.disabled = false;
    }
})();
