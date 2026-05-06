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
    const stopBtn = document.getElementById("stop-btn");

    const uploadSection = document.getElementById("upload-section");
    const confirmSection = document.getElementById("confirm-section");
    const confirmBtn = document.getElementById("confirm-btn");
    const cancelBtn = document.getElementById("cancel-btn");
    const estWords = document.getElementById("est-words");
    const estChunks = document.getElementById("est-chunks");
    const estTokensIn = document.getElementById("est-tokens-in");
    const estTokensOut = document.getElementById("est-tokens-out");
    const estTime = document.getElementById("est-time");
    const estCost = document.getElementById("est-cost");

    const progressSection = document.getElementById("progress-section");
    const statusText = document.getElementById("status-text");
    const timerText = document.getElementById("timer-text");
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
                const originalHTML = shareBtn.innerHTML;
                shareBtn.innerHTML = '<i class="ph ph-check"></i>';
                setTimeout(() => {
                    shareBtn.innerHTML = originalHTML;
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
            const res = await fetch("/api/estimate/", {
                method: "POST",
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                showError(data.error || "Estimation failed.");
                submitBtn.disabled = false;
                return;
            }

            estWords.textContent = data.words;
            if (data.num_tasks && data.num_tasks > data.num_chunks) {
                estChunks.textContent = `${data.num_chunks} (${data.num_tasks} tasks)`;
            } else {
                estChunks.textContent = data.num_chunks;
            }
            estTokensIn.textContent = data.estimated_input_tokens.toLocaleString();
            estTokensOut.textContent = data.estimated_output_tokens.toLocaleString();
            estTime.textContent = data.time_estimate_sec;
            estCost.textContent = data.cost_estimate ? `$${data.cost_estimate.toFixed(3)}` : "Unknown";

            confirmBtn.dataset.jobId = data.job_id;

            uploadSection.hidden = true;
            confirmSection.hidden = false;
            submitBtn.disabled = false;

        } catch (err) {
            showError("Network error: " + err.message);
            submitBtn.disabled = false;
        }
    });

    let timerInterval = null;
    let startTime = 0;

    confirmBtn.addEventListener("click", async () => {
        const jobId = confirmBtn.dataset.jobId;
        if (!jobId) return;

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

        const formData = new FormData();
        formData.append("job_id", jobId);
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

        confirmBtn.disabled = true;
        hideError();

        try {
            const res = await fetch("/api/start/", {
                method: "POST",
                body: formData,
            });

            const data = await res.json();

            if (!res.ok) {
                showError(data.error || "Failed to start.");
                confirmBtn.disabled = false;
                return;
            }

            localStorage.setItem("hjaelper_current_job_id", data.job_id);

            confirmSection.hidden = true;
            progressSection.hidden = false;
            confirmBtn.disabled = false;

            startTime = Date.now();
            timerInterval = setInterval(() => {
                const elapsed = Math.floor((Date.now() - startTime) / 1000);
                const mins = String(Math.floor(elapsed / 60)).padStart(2, '0');
                const secs = String(elapsed % 60).padStart(2, '0');
                timerText.textContent = `Elapsed: ${mins}:${secs}`;
            }, 1000);

            pollStatus(data.job_id);

        } catch (err) {
            showError("Network error: " + err.message);
            confirmBtn.disabled = false;
        }
    });

    cancelBtn.addEventListener("click", () => {
        confirmSection.hidden = true;
        uploadSection.hidden = false;
    });

    // Stop process handler
    stopBtn.addEventListener("click", async () => {
        const jobId = localStorage.getItem("hjaelper_current_job_id");
        if (!jobId) return;

        stopBtn.disabled = true;
        stopBtn.textContent = "STOPPING...";

        try {
            await fetch(`/api/stop/${jobId}/`, { method: "POST" });
            // The poller will pick up the "error" status (Cancelled by user)
        } catch (err) {
            console.error("Failed to stop job:", err);
            stopBtn.disabled = false;
            stopBtn.textContent = "STOP PROCESS";
        }
    });

    // Check for running process on load
    const currentJobId = localStorage.getItem("hjaelper_current_job_id");
    if (currentJobId) {
        uploadSection.hidden = true;
        progressSection.hidden = false;
        pollStatus(currentJobId);
    }

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
                            `${data.completed_chunks} / ${data.total_chunks} tasks`;
                    }
                } else if (data.status === "done") {
                    clearInterval(interval);
                    if (timerInterval) clearInterval(timerInterval);
                    localStorage.removeItem("hjaelper_current_job_id");
                    progressSection.hidden = true;
                    downloadSection.hidden = false;
                    downloadLink.href = `/api/download/${jobId}/`;
                } else if (data.status === "error") {
                    clearInterval(interval);
                    if (timerInterval) clearInterval(timerInterval);
                    localStorage.removeItem("hjaelper_current_job_id");
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
        confirmSection.hidden = true;
        submitBtn.disabled = false;
        confirmBtn.disabled = false;
        stopBtn.disabled = false;
        stopBtn.textContent = "STOP PROCESS";
    }
})();
