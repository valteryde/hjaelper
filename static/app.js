(() => {
    "use strict";

    // DOM elements
    const pdfInput = document.getElementById("pdf-file");
    const apiKeyInput = document.getElementById("api-key");
    const providerSelect = document.getElementById("provider");
    const modelInput = document.getElementById("model");
    const chunkSizeInput = document.getElementById("chunk-size");
    const languageInput = document.getElementById("language");
    const harshnessInput = document.getElementById("harshness");
    const skillLevelInput = document.getElementById("skill-level");
    const customPromptInput = document.getElementById("custom-prompt");
    const submitBtn = document.getElementById("submit-btn");

    // Analysis pass toggles
    const enableThreadInput = document.getElementById("enable-thread");
    const enableCoherenceInput = document.getElementById("enable-coherence");
    const enableFactcheckInput = document.getElementById("enable-factcheck");
    const enableGradingInput = document.getElementById("enable-grading");

    const shareBtn = document.getElementById("share-btn");

    const uploadSection = document.getElementById("upload-section");
    const progressSection = document.getElementById("progress-section");
    const statusText = document.getElementById("status-text");
    const progressFill = document.getElementById("progress-fill");
    const progressDetail = document.getElementById("progress-detail");

    const downloadSection = document.getElementById("download-section");
    const downloadLink = document.getElementById("download-link");

    const errorSection = document.getElementById("error-section");
    const errorText = document.getElementById("error-text");

    // Parse URL hash for settings
    const hash = window.location.hash.slice(1);
    let urlSettings = null;
    if (hash) {
        try {
            urlSettings = JSON.parse(atob(hash));
            // Clear hash so it doesn't linger
            history.replaceState(null, '', window.location.pathname);
        } catch (e) {
            console.error("Failed to parse settings from URL hash");
        }
    }

    // Restore saved values from localStorage or URL hash
    const savedKey = urlSettings?.api_key ?? localStorage.getItem("hjaelper_api_key");
    if (savedKey) apiKeyInput.value = savedKey;

    const savedProvider = urlSettings?.provider ?? localStorage.getItem("hjaelper_provider");
    if (savedProvider) providerSelect.value = savedProvider;

    const savedModel = urlSettings?.model ?? localStorage.getItem("hjaelper_model");
    if (savedModel) modelInput.value = savedModel;

    const savedChunkSize = urlSettings?.chunk_size ?? localStorage.getItem("hjaelper_chunk_size");
    if (savedChunkSize) chunkSizeInput.value = savedChunkSize;

    const savedLanguage = urlSettings?.language ?? localStorage.getItem("hjaelper_language");
    if (savedLanguage) languageInput.value = savedLanguage;

    const savedHarshness = urlSettings?.harshness ?? localStorage.getItem("hjaelper_harshness");
    if (savedHarshness) harshnessInput.value = savedHarshness;

    const savedSkillLevel = urlSettings?.skill_level ?? localStorage.getItem("hjaelper_skill_level");
    if (savedSkillLevel) skillLevelInput.value = savedSkillLevel;

    const savedCustomPrompt = urlSettings?.custom_prompt ?? localStorage.getItem("hjaelper_custom_prompt");
    if (savedCustomPrompt) customPromptInput.value = savedCustomPrompt;

    // Restore toggle states
    const savedThread = urlSettings?.enable_thread ?? localStorage.getItem("hjaelper_enable_thread");
    if (savedThread === "true" || savedThread === true) enableThreadInput.checked = true;

    const savedCoherence = urlSettings?.enable_coherence ?? localStorage.getItem("hjaelper_enable_coherence");
    if (savedCoherence === "true" || savedCoherence === true) enableCoherenceInput.checked = true;

    const savedFactcheck = urlSettings?.enable_factcheck ?? localStorage.getItem("hjaelper_enable_factcheck");
    if (savedFactcheck === "true" || savedFactcheck === true) enableFactcheckInput.checked = true;

    const savedGrading = urlSettings?.enable_grading ?? localStorage.getItem("hjaelper_enable_grading");
    if (savedGrading === "true" || savedGrading === true) enableGradingInput.checked = true;

    // Share settings handler
    shareBtn.addEventListener("click", () => {
        const settings = {
            api_key: apiKeyInput.value.trim(),
            provider: providerSelect.value,
            model: modelInput.value.trim(),
            chunk_size: chunkSizeInput.value,
            language: languageInput.value.trim(),
            harshness: harshnessInput.value.trim(),
            skill_level: skillLevelInput.value.trim(),
            custom_prompt: customPromptInput.value.trim(),
            enable_thread: enableThreadInput.checked,
            enable_coherence: enableCoherenceInput.checked,
            enable_factcheck: enableFactcheckInput.checked,
            enable_grading: enableGradingInput.checked
        };
        
        try {
            const hash = btoa(JSON.stringify(settings));
            const url = `${window.location.origin}${window.location.pathname}#${hash}`;
            
            navigator.clipboard.writeText(url).then(() => {
                const originalText = shareBtn.textContent;
                shareBtn.textContent = "COPIED TO CLIPBOARD!";
                setTimeout(() => {
                    shareBtn.textContent = originalText;
                }, 2000);
            }).catch(() => {
                showError("Failed to copy URL to clipboard.");
            });
        } catch (e) {
            showError("Failed to encode settings.");
        }
    });

    // Upload handler
    submitBtn.addEventListener("click", async () => {
        const file = pdfInput.files[0];
        const apiKey = apiKeyInput.value.trim();
        const provider = providerSelect.value;
        const model = modelInput.value.trim();
        const chunkSize = chunkSizeInput.value;
        const language = languageInput.value.trim();
        const harshness = harshnessInput.value.trim();
        const skillLevel = skillLevelInput.value.trim();
        const customPrompt = customPromptInput.value.trim();
        const enableThread = enableThreadInput.checked;
        const enableCoherence = enableCoherenceInput.checked;
        const enableFactcheck = enableFactcheckInput.checked;
        const enableGrading = enableGradingInput.checked;

        if (!file) return showError("Please select a PDF file.");
        if (!apiKey) return showError("Please enter your API key.");
        if (!model) return showError("Please enter a model name.");

        // Save to localStorage
        localStorage.setItem("hjaelper_api_key", apiKey);
        localStorage.setItem("hjaelper_provider", provider);
        localStorage.setItem("hjaelper_model", model);
        localStorage.setItem("hjaelper_chunk_size", chunkSize);
        localStorage.setItem("hjaelper_language", language);
        localStorage.setItem("hjaelper_harshness", harshness);
        localStorage.setItem("hjaelper_skill_level", skillLevel);
        localStorage.setItem("hjaelper_custom_prompt", customPrompt);
        localStorage.setItem("hjaelper_enable_thread", enableThread);
        localStorage.setItem("hjaelper_enable_coherence", enableCoherence);
        localStorage.setItem("hjaelper_enable_factcheck", enableFactcheck);
        localStorage.setItem("hjaelper_enable_grading", enableGrading);

        // Build FormData
        const formData = new FormData();
        formData.append("pdf", file);
        formData.append("api_key", apiKey);
        formData.append("provider", provider);
        formData.append("model", model);
        formData.append("chunk_size", chunkSize);
        formData.append("language", language);
        formData.append("harshness", harshness);
        formData.append("skill_level", skillLevel);
        formData.append("custom_prompt", customPrompt);
        formData.append("enable_thread", enableThread);
        formData.append("enable_coherence", enableCoherence);
        formData.append("enable_factcheck", enableFactcheck);
        formData.append("enable_grading", enableGrading);

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
