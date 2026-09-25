"""
Assets v4 - CSS Ultra-Aéré pour PromptForge
Design moderne avec beaucoup d'espace et de respiration
"""

# Logo SVG - Plus grand pour le header
LOGO_SVG_LARGE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="56" height="56">
  <defs>
    <linearGradient id="fire" x1="0%" y1="100%" x2="0%" y2="0%">
      <stop offset="0%" style="stop-color:#ff4d00"/>
      <stop offset="100%" style="stop-color:#ffb347"/>
    </linearGradient>
    <linearGradient id="metal" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" style="stop-color:#5a5a5a"/>
      <stop offset="100%" style="stop-color:#2d2d2d"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="12" fill="#1a1a2e"/>
  <ellipse cx="32" cy="50" rx="18" ry="6" fill="#ff6b35" opacity="0.4"/>
  <path d="M18 48 L22 40 L42 40 L46 48 Z" fill="url(#metal)"/>
  <rect x="20" y="36" width="24" height="6" rx="1" fill="#4a4a4a"/>
  <path d="M26 38 L22 42 L26 46" stroke="#ff6b35" stroke-width="2.5" fill="none" stroke-linecap="round"/>
  <path d="M38 38 L42 42 L38 46" stroke="#ff6b35" stroke-width="2.5" fill="none" stroke-linecap="round"/>
  <g transform="rotate(-40, 40, 24)">
    <rect x="36" y="18" width="4" height="24" rx="1" fill="#3d3d3d"/>
    <rect x="30" y="12" width="16" height="8" rx="2" fill="#4a4a4a"/>
  </g>
  <circle cx="28" cy="30" r="2" fill="#ffdd00"/>
  <circle cx="36" cy="28" r="2" fill="#ffaa00"/>
</svg>"""

# CSS Ultra-Aéré
CSS_V4 = """
/* ═══════════════════════════════════════════════════════════════════
   PROMPTFORGE V4 - CSS ULTRA-AÉRÉ
   Design moderne avec BEAUCOUP d'espace et de respiration
   ═══════════════════════════════════════════════════════════════════ */

/* ─────────────────────────────────────────────────────────────────────
   VARIABLES GLOBALES
   ───────────────────────────────────────────────────────────────────── */
:root {
    /* Couleurs principales */
    --primary: #ff6b35;
    --primary-light: #ff8c5a;
    --primary-dark: #e55a2b;
    --primary-glow: rgba(255, 107, 53, 0.25);

    /* Backgrounds */
    --bg-page: #0a0e14;
    --bg-card: #12161d;
    --bg-card-elevated: #181d26;
    --bg-input: #0d1117;
    --bg-hover: #1c222d;

    /* Bordures */
    --border: #2a3140;
    --border-light: #3d4554;
    --border-focus: var(--primary);

    /* Textes */
    --text-primary: #f0f4f8;
    --text-secondary: #9ca3af;
    --text-muted: #6b7280;
    --text-link: var(--primary-light);

    /* États */
    --success: #10b981;
    --success-bg: rgba(16, 185, 129, 0.1);
    --warning: #f59e0b;
    --warning-bg: rgba(245, 158, 11, 0.1);
    --error: #ef4444;
    --error-bg: rgba(239, 68, 68, 0.1);
    --info: #3b82f6;
    --info-bg: rgba(59, 130, 246, 0.1);

    /* Espacements - TRÈS GÉNÉREUX */
    --space-xs: 8px;
    --space-sm: 12px;
    --space-md: 20px;
    --space-lg: 32px;
    --space-xl: 48px;
    --space-2xl: 64px;

    /* Rayons */
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 24px;

    /* Ombres */
    --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.25);
    --shadow-md: 0 4px 20px rgba(0, 0, 0, 0.35);
    --shadow-lg: 0 8px 40px rgba(0, 0, 0, 0.45);
    --shadow-glow: 0 0 30px var(--primary-glow);

    /* Transitions */
    --transition-fast: 0.15s ease;
    --transition-normal: 0.25s ease;
    --transition-slow: 0.4s ease;
}

/* ─────────────────────────────────────────────────────────────────────
   RESET & CONTAINER
   ───────────────────────────────────────────────────────────────────── */
.gradio-container {
    max-width: 1400px !important;
    margin: 0 auto !important;
    padding: var(--space-lg) var(--space-xl) !important;
    background: var(--bg-page) !important;
    min-height: 100vh !important;
}

/* ─────────────────────────────────────────────────────────────────────
   HEADER - GRAND ET ACCUEILLANT
   ───────────────────────────────────────────────────────────────────── */
.pf-header {
    text-align: center;
    padding: var(--space-xl) var(--space-lg);
    margin-bottom: var(--space-xl);
    background: linear-gradient(180deg, var(--bg-card) 0%, transparent 100%);
    border-radius: var(--radius-xl);
    border: 1px solid var(--border);
}

.pf-header-logo {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-md);
    margin-bottom: var(--space-md);
}

.pf-header-logo svg {
    filter: drop-shadow(0 4px 12px var(--primary-glow));
}

.pf-header h1 {
    font-size: 2.75rem;
    font-weight: 800;
    margin: 0;
    background: linear-gradient(135deg, #ffffff 0%, var(--primary) 50%, var(--primary-light) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.02em;
}

.pf-header-tagline {
    font-size: 1.15rem;
    color: var(--text-secondary);
    margin: 0;
    margin-top: var(--space-sm);
}

.pf-header-stats {
    display: flex;
    justify-content: center;
    gap: var(--space-xl);
    margin-top: var(--space-lg);
    padding-top: var(--space-lg);
    border-top: 1px solid var(--border);
}

.pf-stat {
    text-align: center;
}

.pf-stat-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--primary);
    display: block;
}

.pf-stat-label {
    font-size: 0.85rem;
    color: var(--text-muted);
    margin-top: 4px;
}

/* ─────────────────────────────────────────────────────────────────────
   ONBOARDING BANNER
   ───────────────────────────────────────────────────────────────────── */
.pf-onboarding {
    background: linear-gradient(135deg, var(--bg-card) 0%, var(--bg-card-elevated) 100%);
    border: 2px solid var(--primary);
    border-radius: var(--radius-xl);
    padding: var(--space-xl);
    margin-bottom: var(--space-xl);
    box-shadow: var(--shadow-glow);
}

.pf-onboarding-title {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text-primary);
    text-align: center;
    margin-bottom: var(--space-sm);
}

.pf-onboarding-subtitle {
    font-size: 1.1rem;
    color: var(--text-secondary);
    text-align: center;
    margin-bottom: var(--space-xl);
}

.pf-demo-box {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: var(--space-lg);
    align-items: stretch;
    background: var(--bg-page);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-bottom: var(--space-xl);
}

.pf-demo-before,
.pf-demo-after {
    padding: var(--space-lg);
    border-radius: var(--radius-md);
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.9rem;
    line-height: 1.6;
}

.pf-demo-before {
    background: var(--error-bg);
    border: 1px solid var(--error);
}

.pf-demo-after {
    background: var(--success-bg);
    border: 1px solid var(--success);
}

.pf-demo-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: var(--space-sm);
    display: block;
}

.pf-demo-arrow {
    display: flex;
    align-items: center;
    font-size: 2.5rem;
    color: var(--primary);
}

.pf-steps {
    display: flex;
    justify-content: center;
    gap: var(--space-2xl);
}

.pf-step {
    text-align: center;
    max-width: 180px;
}

.pf-step-number {
    width: 48px;
    height: 48px;
    background: var(--primary);
    color: white;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.25rem;
    font-weight: 700;
    margin: 0 auto var(--space-md);
    box-shadow: var(--shadow-md);
}

.pf-step-text {
    color: var(--text-secondary);
    font-size: 0.95rem;
    line-height: 1.5;
}

/* ─────────────────────────────────────────────────────────────────────
   TABS - NAVIGATION CLAIRE
   ───────────────────────────────────────────────────────────────────── */
.tabs {
    border-bottom: 2px solid var(--border) !important;
    margin-bottom: var(--space-xl) !important;
    padding-bottom: 0 !important;
}

button.tab-nav {
    background: transparent !important;
    border: none !important;
    color: var(--text-secondary) !important;
    padding: var(--space-md) var(--space-lg) !important;
    font-size: 1rem !important;
    font-weight: 500 !important;
    border-radius: var(--radius-md) var(--radius-md) 0 0 !important;
    transition: var(--transition-normal) !important;
    margin-right: var(--space-xs) !important;
    position: relative !important;
}

button.tab-nav:hover {
    color: var(--text-primary) !important;
    background: var(--bg-card) !important;
}

button.tab-nav.selected {
    color: var(--primary) !important;
    background: var(--bg-card) !important;
}

button.tab-nav.selected::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 0;
    right: 0;
    height: 3px;
    background: var(--primary);
    border-radius: 3px 3px 0 0;
}

/* ─────────────────────────────────────────────────────────────────────
   CARDS & SECTIONS
   ───────────────────────────────────────────────────────────────────── */
.pf-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-xl);
    margin-bottom: var(--space-lg);
}

.pf-card-elevated {
    background: var(--bg-card-elevated);
    box-shadow: var(--shadow-md);
}

.pf-section-title {
    font-size: 1.35rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: var(--space-lg);
    padding-bottom: var(--space-md);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: var(--space-sm);
}

.pf-section-subtitle {
    font-size: 1rem;
    color: var(--text-secondary);
    margin-bottom: var(--space-lg);
}

/* ─────────────────────────────────────────────────────────────────────
   INPUTS - GRANDS ET LISIBLES
   ───────────────────────────────────────────────────────────────────── */
input[type="text"],
input[type="number"],
textarea,
select {
    background: var(--bg-input) !important;
    border: 2px solid var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: var(--radius-md) !important;
    padding: var(--space-md) var(--space-lg) !important;
    font-size: 1rem !important;
    line-height: 1.5 !important;
    transition: var(--transition-fast) !important;
    width: 100% !important;
}

input:focus,
textarea:focus,
select:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 4px var(--primary-glow) !important;
    outline: none !important;
}

textarea {
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
    min-height: 180px !important;
    resize: vertical !important;
}

/* Labels */
label {
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
    margin-bottom: var(--space-sm) !important;
    display: block !important;
}

/* Espacements entre les champs */
.input-group,
.form-group {
    margin-bottom: var(--space-lg) !important;
}

/* ─────────────────────────────────────────────────────────────────────
   DROPDOWNS
   ───────────────────────────────────────────────────────────────────── */
.wrap {
    background: var(--bg-input) !important;
    border: 2px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
}

.wrap:focus-within {
    border-color: var(--primary) !important;
}

/* ─────────────────────────────────────────────────────────────────────
   BOUTONS - HIÉRARCHIE CLAIRE
   ───────────────────────────────────────────────────────────────────── */
button.primary,
.btn-primary {
    background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%) !important;
    border: none !important;
    color: white !important;
    font-weight: 600 !important;
    font-size: 1.05rem !important;
    padding: var(--space-md) var(--space-xl) !important;
    border-radius: var(--radius-md) !important;
    cursor: pointer !important;
    transition: var(--transition-normal) !important;
    box-shadow: 0 4px 15px var(--primary-glow) !important;
    min-height: 52px !important;
}

button.primary:hover,
.btn-primary:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 25px var(--primary-glow) !important;
}

button.primary:active {
    transform: translateY(0) !important;
}

button.secondary,
.btn-secondary {
    background: transparent !important;
    border: 2px solid var(--border) !important;
    color: var(--text-primary) !important;
    font-weight: 500 !important;
    padding: var(--space-sm) var(--space-lg) !important;
    border-radius: var(--radius-md) !important;
    cursor: pointer !important;
    transition: var(--transition-fast) !important;
    min-height: 44px !important;
}

button.secondary:hover,
.btn-secondary:hover {
    border-color: var(--primary) !important;
    color: var(--primary) !important;
    background: var(--primary-glow) !important;
}

button.stop {
    background: var(--error-bg) !important;
    border: 2px solid var(--error) !important;
    color: var(--error) !important;
}

button.stop:hover {
    background: var(--error) !important;
    color: white !important;
}

/* ─────────────────────────────────────────────────────────────────────
   ACCORDIONS - PLUS D'ESPACE
   ───────────────────────────────────────────────────────────────────── */
.accordion {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-lg) !important;
    margin: var(--space-lg) 0 !important;
    overflow: hidden !important;
}

.accordion > .label-wrap {
    padding: var(--space-lg) var(--space-xl) !important;
    font-size: 1.05rem !important;
    font-weight: 500 !important;
    transition: var(--transition-fast) !important;
}

.accordion > .label-wrap:hover {
    background: var(--bg-hover) !important;
}

.accordion > .content {
    padding: 0 var(--space-xl) var(--space-xl) !important;
}

/* ─────────────────────────────────────────────────────────────────────
   RESULTS & OUTPUT
   ───────────────────────────────────────────────────────────────────── */
.pf-result {
    background: var(--bg-card-elevated);
    border: 2px solid var(--success);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    margin-top: var(--space-lg);
}

.pf-stats-bar {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-lg);
    padding: var(--space-lg);
    background: var(--primary-glow);
    border: 1px solid var(--primary);
    border-radius: var(--radius-md);
    margin-top: var(--space-lg);
}

.pf-stat-chip {
    display: flex;
    align-items: center;
    gap: var(--space-sm);
}

.pf-stat-chip-label {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.pf-stat-chip-value {
    color: var(--primary);
    font-weight: 700;
    font-size: 1.15rem;
}

/* ─────────────────────────────────────────────────────────────────────
   TABLES - LISIBLES
   ───────────────────────────────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    margin: var(--space-lg) 0;
}

th, td {
    padding: var(--space-md) var(--space-lg);
    text-align: left;
    border-bottom: 1px solid var(--border);
}

th {
    background: var(--bg-card-elevated);
    font-weight: 600;
    color: var(--primary);
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

tr:hover td {
    background: var(--bg-hover);
}

/* ─────────────────────────────────────────────────────────────────────
   MARKDOWN - PROSE LISIBLE
   ───────────────────────────────────────────────────────────────────── */
.prose,
.markdown-body {
    color: var(--text-primary);
    line-height: 1.75;
    font-size: 1rem;
}

.prose h1,
.prose h2,
.prose h3,
.prose h4 {
    color: var(--primary) !important;
    margin-top: var(--space-xl) !important;
    margin-bottom: var(--space-md) !important;
    font-weight: 600 !important;
    line-height: 1.3 !important;
}

.prose h1 { font-size: 1.75rem !important; }
.prose h2 { font-size: 1.5rem !important; }
.prose h3 { font-size: 1.25rem !important; }
.prose h4 { font-size: 1.1rem !important; }

.prose p {
    margin-bottom: var(--space-md) !important;
}

.prose ul,
.prose ol {
    margin: var(--space-md) 0 !important;
    padding-left: var(--space-xl) !important;
}

.prose li {
    margin-bottom: var(--space-sm) !important;
}

.prose code {
    background: var(--primary-glow) !important;
    color: var(--primary-light) !important;
    padding: 3px 8px !important;
    border-radius: var(--radius-sm) !important;
    font-size: 0.9em !important;
}

.prose pre {
    background: var(--bg-page) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: var(--space-lg) !important;
    overflow-x: auto !important;
    margin: var(--space-lg) 0 !important;
}

.prose blockquote {
    border-left: 4px solid var(--primary) !important;
    padding: var(--space-md) var(--space-lg) !important;
    margin: var(--space-lg) 0 !important;
    background: var(--primary-glow) !important;
    border-radius: 0 var(--radius-md) var(--radius-md) 0 !important;
}

.prose hr {
    border: none !important;
    height: 1px !important;
    background: var(--border) !important;
    margin: var(--space-xl) 0 !important;
}

.prose strong {
    color: var(--primary-light) !important;
    font-weight: 600 !important;
}

/* ─────────────────────────────────────────────────────────────────────
   SLIDERS
   ───────────────────────────────────────────────────────────────────── */
input[type="range"] {
    height: 8px !important;
    border-radius: 4px !important;
    background: var(--border) !important;
}

/* ─────────────────────────────────────────────────────────────────────
   ROWS & COLUMNS - ESPACEMENT
   ───────────────────────────────────────────────────────────────────── */
.row {
    gap: var(--space-xl) !important;
    margin-bottom: var(--space-lg) !important;
}

.column {
    padding: var(--space-md) !important;
}

/* ─────────────────────────────────────────────────────────────────────
   STATUS MESSAGES
   ───────────────────────────────────────────────────────────────────── */
.pf-status-success {
    background: var(--success-bg);
    border: 1px solid var(--success);
    color: var(--success);
    padding: var(--space-md) var(--space-lg);
    border-radius: var(--radius-md);
    margin: var(--space-md) 0;
}

.pf-status-error {
    background: var(--error-bg);
    border: 1px solid var(--error);
    color: var(--error);
    padding: var(--space-md) var(--space-lg);
    border-radius: var(--radius-md);
    margin: var(--space-md) 0;
}

.pf-status-warning {
    background: var(--warning-bg);
    border: 1px solid var(--warning);
    color: var(--warning);
    padding: var(--space-md) var(--space-lg);
    border-radius: var(--radius-md);
    margin: var(--space-md) 0;
}

/* ─────────────────────────────────────────────────────────────────────
   RESPONSIVE
   ───────────────────────────────────────────────────────────────────── */
@media (max-width: 1024px) {
    .gradio-container {
        padding: var(--space-lg) !important;
    }

    .pf-header h1 {
        font-size: 2rem;
    }

    .pf-demo-box {
        grid-template-columns: 1fr;
    }

    .pf-demo-arrow {
        transform: rotate(90deg);
        justify-content: center;
    }

    .pf-steps {
        flex-direction: column;
        gap: var(--space-lg);
    }
}

@media (max-width: 768px) {
    button.tab-nav {
        padding: var(--space-sm) var(--space-md) !important;
        font-size: 0.9rem !important;
    }

    .pf-header-stats {
        flex-direction: column;
        gap: var(--space-md);
    }
}

/* ─────────────────────────────────────────────────────────────────────
   ANIMATIONS
   ───────────────────────────────────────────────────────────────────── */
@keyframes fadeIn {
    from { opacity: 0; transform: translateY(15px); }
    to { opacity: 1; transform: translateY(0); }
}

@keyframes slideIn {
    from { opacity: 0; transform: translateX(-20px); }
    to { opacity: 1; transform: translateX(0); }
}

@keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 var(--primary-glow); }
    50% { box-shadow: 0 0 0 10px transparent; }
}

.animate-fade-in {
    animation: fadeIn 0.4s ease-out;
}

.animate-slide-in {
    animation: slideIn 0.3s ease-out;
}

.animate-pulse {
    animation: pulse 2s infinite;
}

/* ─────────────────────────────────────────────────────────────────────
   SCROLLBAR
   ───────────────────────────────────────────────────────────────────── */
::-webkit-scrollbar {
    width: 10px;
    height: 10px;
}

::-webkit-scrollbar-track {
    background: var(--bg-page);
}

::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 5px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--primary);
}

/* ─────────────────────────────────────────────────────────────────────
   DARK MODE OVERRIDES (Gradio)
   ───────────────────────────────────────────────────────────────────── */
.dark {
    --background-fill-primary: var(--bg-card) !important;
    --background-fill-secondary: var(--bg-page) !important;
    --border-color-primary: var(--border) !important;
}
"""
