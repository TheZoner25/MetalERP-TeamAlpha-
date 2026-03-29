/**
 * Stremet AI Chat — Frontend logic
 * Handles sidebar toggle, model selection, message sending/streaming, history, and rendering.
 */
(function () {
    'use strict';

    // Detect which layout we are in
    const isOperatorLayout = document.getElementById('operatorLayout') !== null;

    const sidebar = document.getElementById('aiChatSidebar');
    const overlay = document.getElementById('aiChatOverlay');
    const toggle = document.getElementById('aiChatToggle');
    const closeBtn = document.getElementById('aiChatClose');
    const clearBtn = document.getElementById('aiChatClear');
    const messagesEl = document.getElementById('aiChatMessages');
    const welcomeEl = document.getElementById('aiChatWelcome');
    const input = document.getElementById('aiChatInput');
    const sendBtn = document.getElementById('aiChatSend');
    const modelSelect = document.getElementById('aiModelSelect');

    if (!messagesEl || !input || !sendBtn) return;

    let isOpen = isOperatorLayout; // Always open in operator layout
    let isStreaming = false;
    let historyLoaded = false;

    // ── Model Selection ─────────────────────────────────────────────────
    if (modelSelect) {
        const savedModel = localStorage.getItem('aiModel');
        if (savedModel && modelSelect.querySelector(`option[value="${savedModel}"]`)) {
            modelSelect.value = savedModel;
        }
        modelSelect.addEventListener('change', function () {
            localStorage.setItem('aiModel', this.value);
        });
    }

    // ── CSRF Token ─────────────────────────────────────────────────────
    function getCSRFToken() {
        const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    // ── Sidebar Toggle (legacy layout only) ─────────────────────────────
    if (!isOperatorLayout && sidebar && overlay && toggle && closeBtn) {
        function openSidebar() {
            isOpen = true;
            sidebar.classList.add('open');
            overlay.classList.add('active');
            toggle.classList.add('active');
            input.focus();
            if (!historyLoaded) loadHistory();
        }

        function closeSidebar() {
            isOpen = false;
            sidebar.classList.remove('open');
            overlay.classList.remove('active');
            toggle.classList.remove('active');
        }

        function toggleSidebar() {
            isOpen ? closeSidebar() : openSidebar();
        }

        toggle.addEventListener('click', toggleSidebar);
        overlay.addEventListener('click', closeSidebar);
        closeBtn.addEventListener('click', closeSidebar);

        // Cmd/Ctrl + K shortcut
        document.addEventListener('keydown', function (e) {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                toggleSidebar();
            }
            if (e.key === 'Escape' && isOpen) {
                closeSidebar();
            }
        });
    }

    // In operator layout, load history immediately
    if (isOperatorLayout) {
        loadHistory();
    }

    // ── Auto-resize textarea ───────────────────────────────────────────
    input.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
    });

    // ── Send Message ───────────────────────────────────────────────────
    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    sendBtn.addEventListener('click', sendMessage);

    function sendMessage() {
        const text = input.value.trim();
        if (!text || isStreaming) return;

        // Hide welcome
        if (welcomeEl) welcomeEl.style.display = 'none';

        // Add user bubble
        appendMessage('user', text);

        // Clear input
        input.value = '';
        input.style.height = 'auto';

        // Stream response
        streamChat(text);
    }

    // Suggestion clicks
    document.querySelectorAll('.ai-chat-suggestion').forEach(btn => {
        btn.addEventListener('click', function () {
            input.value = this.dataset.msg;
            sendMessage();
        });
    });

    // ── Stream Chat ────────────────────────────────────────────────────
    async function streamChat(message) {
        isStreaming = true;
        sendBtn.disabled = true;

        // Show typing indicator
        const typingEl = showTyping();

        // Abort controller with 120s timeout for long tool chains
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 120000);

        try {
            const resp = await fetch('/api/ai/chat/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                body: JSON.stringify({ message, model: modelSelect.value }),
                signal: controller.signal,
            });

            if (!resp.ok) {
                const err = await resp.json();
                removeTyping(typingEl);
                appendMessage('assistant', 'Error: ' + (err.error || 'Something went wrong.'));
                return;
            }

            removeTyping(typingEl);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let assistantBubble = null;
            let assistantRow = null;
            let toolGroup = null;
            let fullText = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    let payload;
                    try {
                        payload = JSON.parse(line.slice(6));
                    } catch { continue; }

                    if (payload.type === 'text') {
                        // Mark tool group as done when text arrives
                        if (toolGroup && !toolGroup.classList.contains('done')) {
                            toolGroup.classList.add('done');
                        }
                        if (!assistantBubble) {
                            assistantBubble = appendMessage('assistant', '');
                            assistantRow = assistantBubble.parentElement;
                        }
                        fullText += payload.content;
                        assistantBubble.innerHTML = renderMarkdown(fullText);
                        scrollToBottom();
                    } else if (payload.type === 'tool_call') {
                        // Create the assistant row if needed
                        if (!assistantBubble) {
                            assistantBubble = appendMessage('assistant', '');
                            assistantRow = assistantBubble.parentElement;
                        }
                        // Create tool group on first tool call
                        if (!toolGroup) {
                            toolGroup = document.createElement('div');
                            toolGroup.className = 'ai-tool-group';
                            assistantRow.insertBefore(toolGroup, assistantBubble);
                        }
                        // Add tool item to group
                        const item = document.createElement('div');
                        item.className = 'ai-tool-group-item';
                        item.innerHTML = '<span class="tool-dot"></span>' + escapeHtml(payload.name.replace(/_/g, ' '));
                        toolGroup.appendChild(item);
                        scrollToBottom();
                    } else if (payload.type === 'ui_command') {
                        // Dispatch a custom event for the pipeline page to handle
                        document.dispatchEvent(new CustomEvent('pipeline_command', { detail: payload }));
                    } else if (payload.type === 'store_update') {
                        // Real-time update: mark delivery row as STORED in the table
                        var row = document.querySelector('tr[data-delivery-id="' + payload.delivery_id + '"]');
                        if (row) {
                            var badge = row.querySelector('.status-badge');
                            if (badge) {
                                badge.textContent = 'STORED';
                                badge.className = 'status-badge stored';
                            }
                            var progress = row.querySelector('.op-progress');
                            if (progress) {
                                progress.textContent = payload.pallets_stored + '/' + payload.pallets_stored;
                            }
                            var storeBtn = row.querySelector('.op-btn-store');
                            if (storeBtn) {
                                var actionTd = storeBtn.parentElement;
                                storeBtn.remove();
                                actionTd.innerHTML = '<span style="color: var(--op-green); font-size: 12px;">done</span>';
                            }
                        }
                    } else if (payload.type === 'done') {
                        if (toolGroup) toolGroup.classList.add('done');
                    } else if (payload.type === 'error') {
                        if (toolGroup) toolGroup.classList.add('done');
                        if (!assistantBubble) {
                            assistantBubble = appendMessage('assistant', '');
                            assistantRow = assistantBubble.parentElement;
                        }
                        fullText += '\n\n**Error:** ' + payload.content;
                        assistantBubble.innerHTML = renderMarkdown(fullText);
                    }
                }
            }
        } catch (err) {
            removeTyping(typingEl);
            const msg = err.name === 'AbortError'
                ? 'Request timed out. The AI took too long to respond — please try again.'
                : 'Connection error: ' + (err.message || 'Please try again.');
            appendMessage('assistant', msg);
        } finally {
            clearTimeout(timeout);
            isStreaming = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }

    // ── Load History ───────────────────────────────────────────────────
    async function loadHistory() {
        historyLoaded = true;
        try {
            const resp = await fetch('/api/ai/chat/history/');
            const data = await resp.json();
            if (data.messages && data.messages.length > 0) {
                if (welcomeEl) welcomeEl.style.display = 'none';
                data.messages.forEach(m => {
                    appendMessage(m.role, m.content, true);
                });
                scrollToBottom();
            }
        } catch (e) {
            // silently fail
        }
    }

    // ── Clear Conversation ─────────────────────────────────────────────
    if (clearBtn) clearBtn.addEventListener('click', async function () {
        try {
            await fetch('/api/ai/chat/clear/', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCSRFToken() },
            });
        } catch (e) { /* */ }

        // Clear UI
        messagesEl.innerHTML = '';
        messagesEl.appendChild(welcomeEl);
        welcomeEl.style.display = '';
        historyLoaded = false;
    });

    // ── DOM Helpers ────────────────────────────────────────────────────
    function appendMessage(role, content, isHistory) {
        const row = document.createElement('div');
        row.className = 'ai-msg-row ' + role;

        // Add AI avatar for assistant messages
        if (role === 'assistant') {
            const avatar = document.createElement('div');
            avatar.className = 'ai-msg-avatar';
            avatar.innerHTML = '';
            row.appendChild(avatar);
        }

        const bubble = document.createElement('div');
        bubble.className = 'ai-msg-bubble';

        if (role === 'assistant') {
            bubble.innerHTML = isHistory ? renderMarkdown(content) : content;
        } else {
            bubble.textContent = content;
        }

        row.appendChild(bubble);
        messagesEl.appendChild(row);
        scrollToBottom();
        return bubble;
    }

    function showTyping() {
        const el = document.createElement('div');
        el.className = 'ai-typing';
        el.innerHTML = '<div class="ai-typing-dot"></div><div class="ai-typing-dot"></div><div class="ai-typing-dot"></div>';
        messagesEl.appendChild(el);
        scrollToBottom();
        return el;
    }

    function removeTyping(el) {
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // ── Markdown Renderer ───────────────────────────────────────────────
    function renderMarkdown(text) {
        // Step 1: Extract fenced code blocks BEFORE escaping
        const codeBlocks = [];
        text = text.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
            const idx = codeBlocks.length;
            codeBlocks.push('<pre class="md-code-block"><code>' + escapeHtml(code.trimEnd()) + '</code></pre>');
            return '\n%%CODEBLOCK_' + idx + '%%\n';
        });

        // Step 2: Escape HTML in remaining text
        let html = escapeHtml(text);

        // Step 3: Headings (must be at start of line)
        html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

        // Step 4: Horizontal rules
        html = html.replace(/^---+$/gm, '<hr>');

        // Step 5: Bold (before italic to avoid conflicts)
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

        // Step 5b: Bold with __ syntax
        html = html.replace(/__(.+?)__/g, '<strong>$1</strong>');

        // Step 6: Italic (only inline, not at start of line — those are list items handled in Step 9)
        html = html.replace(/(?<![*\w])\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)/g, '<em>$1</em>');

        // Step 7: Inline code
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Step 8: Tables
        html = html.replace(/((?:^|\n)\|.+\|(?:\n\|.+\|)+)/g, function(tableBlock) {
            const lines = tableBlock.trim().split('\n').filter(l => l.trim());
            if (lines.length < 2) return tableBlock;

            let table = '<table>';
            let headerDone = false;
            lines.forEach((line, i) => {
                // Skip separator rows
                if (/^\|[\s\-:|\s]+\|?$/.test(line.trim())) {
                    if (!headerDone) {
                        table += '</thead><tbody>';
                        headerDone = true;
                    }
                    return;
                }
                const cells = line.split('|').filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
                if (i === 0) {
                    table += '<thead><tr>' + cells.map(c => '<th>' + c.trim() + '</th>').join('') + '</tr>';
                    if (lines.length === 1 || !/^\|[\s\-:|\s]+\|?$/.test((lines[1] || '').trim())) {
                        table += '</thead><tbody>';
                        headerDone = true;
                    }
                } else {
                    table += '<tr>' + cells.map(c => '<td>' + c.trim() + '</td>').join('') + '</tr>';
                }
            });
            table += '</tbody></table>';
            return table;
        });

        // Step 9: Unordered lists — handle consecutive lines starting with -, •, or *
        // Also handle sub-items indented with spaces
        html = html.replace(/((?:^|\n)[ \t]*[-•*] .+(?:\n[ \t]*[-•*] .+)*)/g, function(block) {
            const lines = block.trim().split('\n');
            let list = '<ul>';
            for (const l of lines) {
                list += '<li>' + l.replace(/^[ \t]*[-•*] /, '') + '</li>';
            }
            list += '</ul>';
            return list;
        });

        // Step 10: Ordered lists
        html = html.replace(/((?:^|\n)\d+\. .+(?:\n\d+\. .+)*)/g, function(block) {
            const lines = block.trim().split('\n');
            let list = '<ol>';
            for (const l of lines) {
                list += '<li>' + l.replace(/^\d+\. /, '') + '</li>';
            }
            list += '</ol>';
            return list;
        });

        // Step 11: Paragraphs — double newlines
        html = html.replace(/\n\n+/g, '</p><p>');
        html = '<p>' + html + '</p>';

        // Clean up empty paragraphs and paragraphs wrapping block elements
        html = html.replace(/<p>\s*<\/p>/g, '');
        html = html.replace(/<p>\s*(<h[1-4]>)/g, '$1');
        html = html.replace(/(<\/h[1-4]>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<hr>)/g, '$1');
        html = html.replace(/(<hr>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<ul>)/g, '$1');
        html = html.replace(/(<\/ul>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<ol>)/g, '$1');
        html = html.replace(/(<\/ol>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(<table>)/g, '$1');
        html = html.replace(/(<\/table>)\s*<\/p>/g, '$1');
        html = html.replace(/<p>\s*(%%CODEBLOCK_\d+%%)\s*<\/p>/g, '$1');

        // Step 12: Single newlines to <br>
        // Replace all \n with <br> except those directly after block-level closing tags
        html = html.replace(/\n/g, '<br>');
        // Clean up <br> directly adjacent to block elements (no double breaks around blocks)
        html = html.replace(/<br>\s*(<\/?(h[1-4]|hr|ul|ol|li|table|thead|tbody|tr|td|th|p|pre|div)[\s>])/gi, '$1');
        html = html.replace(/(<\/?(h[1-4]|hr|ul|ol|li|table|thead|tbody|tr|td|th|p|pre|div)>)\s*<br>/gi, '$1');

        // Step 13: Re-inject code blocks
        codeBlocks.forEach((block, i) => {
            html = html.replace('%%CODEBLOCK_' + i + '%%', block);
        });

        return html;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
})();
