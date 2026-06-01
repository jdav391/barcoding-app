document.addEventListener("DOMContentLoaded", function() {
    document.body.addEventListener("htmx:afterSwap", function(evt) {
        if (evt.detail.target.id === "wizard-content") {
            updateWizardSteps();
        }
    });

    document.addEventListener("click", function(e) {
        var stepEl = e.target.closest(".wizard-steps .step.done, .wizard-steps .step.clickable");
        if (!stepEl) return;
        var targetStep = parseInt(stepEl.dataset.step);
        var currentStep = getCurrentWizardStep();
        if (targetStep >= currentStep || targetStep < 1) return;
        var sessionId = getWizardSessionId();
        if (!sessionId) return;

        var form = document.getElementById("wizard-nav");
        if (form) {
            htmx.ajax("POST", "/wizard/" + sessionId + "/goto/" + targetStep, {
                source: form,
                target: "#wizard-content",
                swap: "innerHTML",
                values: getWizardFormValues(form)
            });
        }
    });
});

function getCurrentWizardStep() {
    var el = document.querySelector("[data-wizard-step]");
    return el ? parseInt(el.dataset.wizardStep) : 0;
}

function getWizardSessionId() {
    var el = document.querySelector('#wizard-nav input[name="session_id"], input[name="session_id"]');
    return el ? el.value : "";
}

function getWizardFormValues(form) {
    var values = {};
    new FormData(form).forEach(function(v, k) { values[k] = v; });
    return values;
}

function updateWizardSteps() {
    var active = document.querySelector("[data-wizard-step]");
    if (!active) return;
    var step = parseInt(active.dataset.wizardStep);
    document.querySelectorAll(".wizard-steps .step").forEach(function(el) {
        var s = parseInt(el.dataset.step);
        el.classList.toggle("active", s === step);
        el.classList.toggle("done", s < step);
    });
}

function saveAndExit() {
    var form = document.getElementById("wizard-nav");
    if (!form) return;

    var tempForm = document.createElement("form");
    tempForm.method = "POST";
    tempForm.action = "/wizard/save-and-exit";
    tempForm.style.display = "none";

    new FormData(form).forEach(function(value, key) {
        var input = document.createElement("input");
        input.type = "hidden";
        input.name = key;
        input.value = value;
        tempForm.appendChild(input);
    });

    var stepEl = document.querySelector("[data-wizard-step]");
    var stepInput = document.createElement("input");
    stepInput.type = "hidden";
    stepInput.name = "current_step";
    stepInput.value = stepEl ? stepEl.dataset.wizardStep : "1";
    tempForm.appendChild(stepInput);

    document.body.appendChild(tempForm);
    tempForm.submit();
}

function connectJobWebSocket(jobId) {
    var ws = new WebSocket("ws://" + window.location.host + "/api/jobs/" + jobId + "/ws");
    var bar = document.getElementById("progress-fill");
    var msg = document.getElementById("progress-message");

    ws.onmessage = function(event) {
        var data = JSON.parse(event.data);
        if (bar && data.total > 0) {
            bar.style.width = Math.round((data.current / data.total) * 100) + "%";
        }
        if (msg) {
            msg.textContent = data.message || "";
        }
        if (data.status === "complete") {
            window.location.href = "/jobs/" + jobId + "/report";
        }
        if (data.status === "error") {
            if (msg) msg.textContent = "Error: " + data.message;
        }
    };
}

function browseTo(path) {
    if (!path) return;
    document.getElementById("browse-path").value = path;
    var list = document.getElementById("file-list");
    list.innerHTML = "<p>Loading...</p>";

    fetch("/api/files/browse?path=" + encodeURIComponent(path))
        .then(function(r) {
            if (!r.ok) throw new Error("Could not browse: " + r.statusText);
            return r.json();
        })
        .then(function(entries) {
            var html = "";
            var parts = path.replace(/\/+$/, "").split("/");
            if (parts.length > 1) {
                var parent = parts.slice(0, -1).join("/") || "/";
                html += '<div class="entry" onclick="browseTo(\'' + parent.replace(/'/g, "\\'") + '\')">..</div>';
            }
            entries.forEach(function(e) {
                if (e.is_dir) {
                    html += '<div class="entry" onclick="browseTo(\'' + e.path.replace(/'/g, "\\'") + '\')">📁 ' + e.name + '</div>';
                } else {
                    html += '<div class="entry" onclick="selectPdf(\'' + e.path.replace(/'/g, "\\'") + '\')">📄 ' + e.name + '</div>';
                }
            });
            if (!entries.length) html += "<p>No PDF files or subdirectories found.</p>";
            list.innerHTML = html;
        })
        .catch(function(err) {
            list.innerHTML = "<p>" + err.message + "</p>";
        });
}

function uploadSourcePdf(input) {
    if (!input.files || !input.files[0]) return;
    var file = input.files[0];
    var status = document.getElementById("upload-status");
    var info = document.getElementById("selected-file-info");
    status.textContent = "Uploading " + file.name + "...";
    info.textContent = "";

    var formData = new FormData();
    formData.append("file", file);

    fetch("/api/files/upload", { method: "POST", body: formData })
        .then(function(r) {
            if (!r.ok) throw new Error("Upload failed: " + r.statusText);
            return r.json();
        })
        .then(function(data) {
            document.getElementById("source-path").value = data.path;
            document.getElementById("btn-next-source").disabled = false;
            status.textContent = "";
            info.textContent = "Selected: " + data.name + " (" + data.page_count + " pages)";
        })
        .catch(function(err) {
            status.textContent = "Error: " + err.message;
        });
}

function uploadSourcePdfs(input) {
    if (!input.files || input.files.length === 0) return;
    var files = Array.from(input.files);
    var status = document.getElementById("upload-status");
    var fileList = document.getElementById("uploaded-files-list");
    var info = document.getElementById("selected-file-info");
    var uploadedPaths = [];
    var completed = 0;
    var total = files.length;

    status.textContent = "Uploading " + total + " file(s)...";
    info.textContent = "";
    fileList.innerHTML = "";

    files.forEach(function(file) {
        var formData = new FormData();
        formData.append("file", file);

        fetch("/api/files/upload", { method: "POST", body: formData })
            .then(function(r) {
                if (!r.ok) throw new Error("Upload failed: " + file.name);
                return r.json();
            })
            .then(function(data) {
                uploadedPaths.push({
                    path: data.path,
                    name: data.name,
                    page_count: data.page_count,
                });
                completed++;
                status.textContent = "Uploaded " + completed + " of " + total + "...";

                if (completed === total) {
                    uploadedPaths.sort(function(a, b) {
                        return a.name.localeCompare(b.name);
                    });

                    if (uploadedPaths.length === 1) {
                        document.getElementById("source-path").value = uploadedPaths[0].path;
                        document.getElementById("source-paths").value = JSON.stringify(uploadedPaths);
                        info.textContent = "Selected: " + uploadedPaths[0].name + " (" + uploadedPaths[0].page_count + " pages)";
                    } else {
                        document.getElementById("source-path").value = "";
                        document.getElementById("source-paths").value = JSON.stringify(uploadedPaths);
                        info.textContent = uploadedPaths.length + " PDFs selected";

                        var html = '<table><thead><tr><th>File</th><th>Pages</th></tr></thead><tbody>';
                        uploadedPaths.forEach(function(p) {
                            html += '<tr><td>' + p.name + '</td><td>' + p.page_count + '</td></tr>';
                        });
                        html += '</tbody></table>';
                        fileList.innerHTML = html;
                    }

                    document.getElementById("btn-next-source").disabled = false;
                    status.textContent = "";
                }
            })
            .catch(function(err) {
                completed++;
                status.textContent = "Error uploading " + file.name + ": " + err.message;
            });
    });
}

function selectPdf(path) {
    document.getElementById("source-path").value = path;
    var info = document.getElementById("selected-file-info");
    info.textContent = "Selected: " + path;
    document.getElementById("btn-next-source").disabled = false;

    fetch("/api/files/info?path=" + encodeURIComponent(path))
        .then(function(r) { return r.ok ? r.json() : null; })
        .then(function(data) {
            if (data && data.page_count) {
                info.textContent = "Selected: " + path + " (" + data.page_count + " pages)";
                var pathsEl = document.getElementById("source-paths");
                if (pathsEl) {
                    pathsEl.value = JSON.stringify([{
                        path: path,
                        name: data.name,
                        page_count: data.page_count,
                    }]);
                }
            }
        });
}

function addManualEntry() {
    var form = document.getElementById("manual-form");
    var data = new FormData(form);
    var entry = {
        batch_id: data.get("batch_id"),
        expected_letters: parseInt(data.get("expected_letters")),
        expected_sheets: parseInt(data.get("expected_sheets")),
        sheets_per_doc: data.get("sheets_per_doc") ? parseInt(data.get("sheets_per_doc")) : null,
        print_type: data.get("print_type") || null,
        has_insert: !!data.get("has_insert"),
        insert_description: null,
        source_filename: null
    };

    var existing = JSON.parse(document.getElementById("batch-data-json").value || "[]");
    existing.push(entry);
    document.getElementById("batch-data-json").value = JSON.stringify(existing);

    var preview = document.getElementById("batch-preview");
    var table = preview.querySelector("table");
    if (!table) {
        preview.innerHTML = '<table><thead><tr><th>Batch ID</th><th>Letters</th><th>Sheets</th><th>Sheets/Doc</th><th>Insert</th></tr></thead><tbody></tbody></table>';
        table = preview.querySelector("table");
    }
    var tbody = table.querySelector("tbody");
    var row = tbody.insertRow();
    row.innerHTML = "<td>" + entry.batch_id + "</td><td>" + entry.expected_letters + "</td><td>" + entry.expected_sheets + "</td><td>" + (entry.sheets_per_doc || "—") + "</td><td>" + (entry.has_insert ? "Yes" : "No") + "</td>";
    form.reset();
}

function sendCertification(jobId) {
    var recipients = document.getElementById("cert-recipients").value;
    var status = document.getElementById("cert-status");
    var btn = document.getElementById("btn-send-cert");

    if (!recipients.trim()) {
        status.textContent = "Please enter at least one recipient.";
        return;
    }

    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    status.textContent = "Sending...";

    fetch("/api/jobs/" + jobId + "/report/send", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({recipients: recipients}),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status === "sent") {
            status.textContent = "Certification email sent successfully.";
            status.style.color = "var(--pico-ins-color)";
        } else {
            status.textContent = "Failed to send email. Check SMTP settings.";
            status.style.color = "var(--pico-del-color)";
        }
    })
    .catch(function(err) {
        status.textContent = "Error: " + err.message;
        status.style.color = "var(--pico-del-color)";
    })
    .finally(function() {
        btn.disabled = false;
        btn.removeAttribute("aria-busy");
    });
}

function processJobQueue(jobIds, sessionId, outputMode) {
    var currentIndex = 0;
    var total = jobIds.length;
    var label = document.getElementById("progress-job-label");
    var bar = document.getElementById("progress-fill");
    var msg = document.getElementById("progress-message");

    function processNext() {
        if (currentIndex >= total) {
            if (outputMode === "COMBINED" && total > 1) {
                msg.textContent = "Compiling session...";
                fetch("/api/sessions/" + sessionId + "/compile", { method: "POST" })
                    .then(function(r) { return r.json(); })
                    .then(function() {
                        window.location.href = "/sessions/" + sessionId;
                    })
                    .catch(function() {
                        window.location.href = "/sessions/" + sessionId;
                    });
            } else {
                window.location.href = "/sessions/" + sessionId;
            }
            return;
        }

        var jobId = jobIds[currentIndex];
        label.textContent = "Job " + (currentIndex + 1) + " of " + total;
        bar.style.width = "0%";
        msg.textContent = "Starting job " + (currentIndex + 1) + "...";

        var ws = new WebSocket("ws://" + window.location.host + "/api/jobs/" + jobId + "/ws");

        ws.onmessage = function(event) {
            var data = JSON.parse(event.data);
            if (bar && data.total > 0) {
                bar.style.width = Math.round((data.current / data.total) * 100) + "%";
            }
            if (msg) {
                msg.textContent = data.message || "";
            }
            if (data.status === "complete") {
                currentIndex++;
                processNext();
            }
            if (data.status === "error") {
                if (msg) msg.textContent = "Error on job " + (currentIndex + 1) + ": " + data.message;
                currentIndex++;
                setTimeout(processNext, 2000);
            }
        };

        ws.onerror = function() {
            msg.textContent = "WebSocket error on job " + (currentIndex + 1) + ". Retrying via HTTP...";
            fetch("/api/jobs/" + jobId + "/run", { method: "POST" })
                .then(function() {
                    currentIndex++;
                    processNext();
                })
                .catch(function(err) {
                    msg.textContent = "Failed: " + err.message;
                    currentIndex++;
                    setTimeout(processNext, 2000);
                });
        };
    }

    processNext();
}
