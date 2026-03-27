import { useState, useEffect } from "react";

// ── helpers ──────────────────────────────────────────────────────────────────

const normalizeAiText = (text) => {
  if (!text) return "";
  let cleaned = text;
  cleaned = cleaned.replace(/(\*\*|__)(.*?)\1/g, "$2");
  cleaned = cleaned.replace(/(\*|_)(.*?)\1/g, "$2");
  cleaned = cleaned.replace(/`{1,3}(.*?)`{1,3}/g, "$1");
  cleaned = cleaned.replace(/^\s*#{1,6}\s+/gm, "");
  cleaned = cleaned.replace(/\n{3,}/g, "\n\n");
  return cleaned.trim();
};

const API = process.env.REACT_APP_API_URL || "http://127.0.0.1:5000";

// ── Section component (collapsible) ──────────────────────────────────────────

const Section = ({ title, color, children, defaultOpen = false }) => {
  const [open, setOpen] = useState(defaultOpen);

  const borders = {
    gray: "border-gray-700", red: "border-red-800",
    blue: "border-blue-800", purple: "border-purple-800", yellow: "border-yellow-800",
  };
  const titles = {
    gray: "text-gray-300", red: "text-red-400",
    blue: "text-blue-400", purple: "text-purple-400", yellow: "text-yellow-400",
  };

  return (
    <div className={`rounded-xl border ${borders[color]} bg-gray-900 overflow-hidden`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-800 transition-colors duration-150"
      >
        <span className={`text-sm font-semibold uppercase tracking-widest ${titles[color]}`}>{title}</span>
        <span className="text-gray-500 text-lg">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="px-5 pb-5 border-t border-gray-800">
          <div className="pt-4 text-gray-100 text-base leading-8 whitespace-pre-wrap">{children}</div>
        </div>
      )}
    </div>
  );
};

// ── File tree component ───────────────────────────────────────────────────────

const FileTree = ({ tree, onSelectFile, selectedPath }) => {
  const folders = {};
  const files = [];

  tree.forEach((item) => {
    if (item.type === "blob") {
      const parts = item.path.split("/");
      if (parts.length === 1) {
        files.push(item);
      } else {
        const folder = parts[0];
        if (!folders[folder]) folders[folder] = [];
        folders[folder].push(item);
      }
    }
  });

  return (
    <div className="text-sm font-mono">
      {Object.entries(folders).map(([folder, items]) => (
        <FolderNode
          key={folder}
          folder={folder}
          items={items}
          onSelectFile={onSelectFile}
          selectedPath={selectedPath}
        />
      ))}
      {files.map((file) => (
        <FileNode
          key={file.path}
          file={file}
          onSelectFile={onSelectFile}
          selected={selectedPath === file.path}
        />
      ))}
    </div>
  );
};

const FolderNode = ({ folder, items, onSelectFile, selectedPath }) => {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-800 rounded text-gray-400 text-left"
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>{folder}/</span>
      </button>
      {open && (
        <div className="ml-4 border-l border-gray-800 pl-2">
          {items.map((file) => (
            <FileNode
              key={file.path}
              file={file}
              onSelectFile={onSelectFile}
              selected={selectedPath === file.path}
            />
          ))}
        </div>
      )}
    </div>
  );
};

const FileNode = ({ file, onSelectFile, selected }) => {
  const ext = file.path.split(".").pop();
  const icons = {
    py: "🐍", js: "🟨", ts: "🔷", jsx: "⚛️", tsx: "⚛️",
    json: "📋", md: "📝", css: "🎨", html: "🌐", go: "🐹",
    rs: "🦀", java: "☕", cpp: "⚙️", c: "⚙️",
  };
  const icon = icons[ext] || "📄";

  return (
    <button
      onClick={() => onSelectFile(file)}
      className={`w-full flex items-center gap-2 px-3 py-1.5 rounded text-left transition-colors ${
        selected ? "bg-blue-900/40 text-blue-300" : "hover:bg-gray-800 text-gray-400"
      }`}
    >
      <span>{icon}</span>
      <span className="truncate">{file.path.split("/").pop()}</span>
    </button>
  );
};

// ── Main App ──────────────────────────────────────────────────────────────────

function App() {
  const [mode, setMode] = useState("snippet"); // "snippet" | "repo"

  // Auth state
  const [githubToken, setGithubToken] = useState(null);
  const [githubUser, setGithubUser] = useState(null);

  // API key state — persisted in localStorage
  const [anthropicKey, setAnthropicKey] = useState(() => localStorage.getItem("anthropic_key") || "");
  const [showKeyPanel, setShowKeyPanel] = useState(false);
  const [keyDraft, setKeyDraft] = useState("");

  const saveKey = () => {
    const trimmed = keyDraft.trim();
    localStorage.setItem("anthropic_key", trimmed);
    setAnthropicKey(trimmed);
    setShowKeyPanel(false);
    setKeyDraft("");
  };

  const removeKey = () => {
    localStorage.removeItem("anthropic_key");
    setAnthropicKey("");
  };

  // Snippet mode state
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("python");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showScoreDetails, setShowScoreDetails] = useState(false);

  // Repo mode state
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [repoTree, setRepoTree] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState("");
  const [repoResult, setRepoResult] = useState(null);
  const [repoSummary, setRepoSummary] = useState(null);
  const [readmeContent, setReadmeContent] = useState("");
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [repoLoading, setRepoLoading] = useState(false);

  // ── Read GitHub token from URL on first load ──
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    const login = params.get("login");
    const avatar = params.get("avatar");

    if (token) {
      setGithubToken(token);
      setGithubUser({ login, avatar_url: avatar });
      // Clean the URL so the token isn't visible
      window.history.replaceState({}, "", "/");
      setMode("repo");
    }
  }, []);

  // ── Snippet mode submit ──
  const handleSubmit = async () => {
    if (!code.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await fetch(`${API}/review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(githubToken ? { Authorization: `Bearer ${githubToken}` } : {}),
          ...(anthropicKey ? { "X-Api-Key": anthropicKey } : {}),
        },
        body: JSON.stringify({ code, language }),
      });
      const data = await response.json();
      if (!response.ok) { setError(data.error || "Something went wrong"); return; }
      setResult(data);
    } catch {
      setError("Could not connect to the server. Is your backend running?");
    } finally {
      setLoading(false);
    }
  };

  // ── Load repos after GitHub login ──
useEffect(() => {
    if (!githubToken) return;
    const loadRepos = async () => {
      setRepoLoading(true);
      try {
        const res = await fetch(`${API}/github/repos`, {
          headers: { Authorization: `Bearer ${githubToken}` },
        });
        const data = await res.json();
        setRepos(data);
      } catch {
        console.error("Failed to load repos");
      } finally {
        setRepoLoading(false);
      }
    };
    loadRepos();
  }, [githubToken]);

  // ── Select a repo and load its file tree ──
  const handleSelectRepo = async (repo) => {
    setSelectedRepo(repo);
    setSelectedFile(null);
    setFileContent("");
    setRepoResult(null);
    setRepoSummary(null);
    setReadmeContent("");
    setRepoTree([]);

    const [owner, repoName] = repo.full_name.split("/");
    try {
      const res = await fetch(
        `${API}/github/tree?owner=${owner}&repo=${repoName}`,
        { headers: { Authorization: `Bearer ${githubToken}` } }
      );
      const data = await res.json();
      const tree = data.tree || [];
      setRepoTree(tree);

      const readmeFile = tree.find(
        (item) => item.type === "blob" && /^readme\.md$/i.test(item.path)
      );
      if (readmeFile) {
        const readmeRes = await fetch(
          `${API}/github/file?owner=${owner}&repo=${repoName}&path=${encodeURIComponent(readmeFile.path)}`,
          { headers: { Authorization: `Bearer ${githubToken}` } }
        );
        const readmeData = await readmeRes.json();
        setReadmeContent(readmeData.decoded_content || "");
      }
    } catch {
      console.error("Failed to load repo tree");
    }
  };

  // ── Select a file and get AI explanation ──
  const handleSelectFile = async (file) => {
    setSelectedFile(file);
    setFileContent("");
    setRepoResult(null);
    setFileLoading(true);

    const [owner, repoName] = selectedRepo.full_name.split("/");

    try {
      const res = await fetch(
        `${API}/github/file?owner=${owner}&repo=${repoName}&path=${encodeURIComponent(file.path)}`,
        { headers: { Authorization: `Bearer ${githubToken}` } }
      );
      const data = await res.json();
      const content = data.decoded_content || "";
      setFileContent(content);

      const reviewRes = await fetch(`${API}/review`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(githubToken ? { Authorization: `Bearer ${githubToken}` } : {}),
          ...(anthropicKey ? { "X-Api-Key": anthropicKey } : {}),
        },
        body: JSON.stringify({
          code: content.slice(0, 4000),
          language: file.path.split(".").pop() || "unknown",
        }),
      });
      const reviewData = await reviewRes.json();
      setRepoResult(reviewData);
    } catch {
      setRepoResult(null);
    } finally {
      setFileLoading(false);
    }
  };

  // ── Summarize entire repo architecture ──
  const handleExplainRepo = async () => {
    if (!selectedRepo || !githubToken) return;
    setSummaryLoading(true);
    setRepoSummary(null);
    const [owner, repoName] = selectedRepo.full_name.split("/");
    try {
      const res = await fetch(`${API}/github/explain-repo`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${githubToken}`,
          ...(anthropicKey ? { "X-Api-Key": anthropicKey } : {}),
        },
        body: JSON.stringify({ owner, repo: repoName }),
      });
      const data = await res.json();
      setRepoSummary(data);
    } catch {
      setRepoSummary({ error: "Failed to analyze repo." });
    } finally {
      setSummaryLoading(false);
    }
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">

      {/* Top Bar */}
      <div className="border-b border-gray-800 px-8 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">CodeLens</h1>
          <p className="text-gray-500 text-xs mt-0.5">AI-powered code intelligence</p>
        </div>

        <div className="flex items-center gap-4">
          {/* Mode Toggle */}
          <div className="flex bg-gray-900 border border-gray-700 rounded-lg p-1">
            <button
              onClick={() => setMode("snippet")}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === "snippet" ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Snippet Review
            </button>
            <button
              onClick={() => setMode("repo")}
              className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
                mode === "repo" ? "bg-blue-600 text-white" : "text-gray-400 hover:text-gray-200"
              }`}
            >
              Repo Intelligence
            </button>
          </div>

          {/* Anthropic API Key */}
          <div className="relative">
            <button
              onClick={() => { setShowKeyPanel((p) => !p); setKeyDraft(anthropicKey); }}
              className={`flex items-center gap-2 border text-sm font-medium px-3 py-2 rounded-lg transition-colors ${
                anthropicKey
                  ? "bg-green-900/30 border-green-700 text-green-400 hover:bg-green-900/50"
                  : "bg-yellow-900/30 border-yellow-700 text-yellow-400 hover:bg-yellow-900/50"
              }`}
            >
              {anthropicKey ? "API Key ✓" : "Add API Key"}
            </button>

            {showKeyPanel && (
              <div className="absolute right-0 top-full mt-2 w-80 bg-gray-900 border border-gray-700 rounded-xl p-4 z-50 shadow-2xl">
                <p className="text-xs text-gray-400 mb-1 font-semibold">Anthropic API Key</p>
                <p className="text-xs text-gray-600 mb-3">Stored in your browser only. Never sent to our server except to call Claude.</p>
                <input
                  type="password"
                  value={keyDraft}
                  onChange={(e) => setKeyDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && saveKey()}
                  placeholder="sk-ant-..."
                  className="w-full bg-gray-800 text-gray-100 text-sm rounded-lg px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500 font-mono mb-3"
                />
                <div className="flex gap-2">
                  <button onClick={saveKey} className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold py-1.5 rounded-lg transition-colors">
                    Save
                  </button>
                  {anthropicKey && (
                    <button onClick={removeKey} className="flex-1 bg-gray-800 hover:bg-red-900/40 text-gray-400 hover:text-red-400 text-xs font-semibold py-1.5 rounded-lg transition-colors border border-gray-700">
                      Remove
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* GitHub Auth */}
          {githubUser ? (
            <div className="flex items-center gap-2">
              <img src={githubUser.avatar_url} alt="avatar" className="w-7 h-7 rounded-full" />
              <span className="text-gray-300 text-sm">{githubUser.login}</span>
              <button
                onClick={() => { setGithubToken(null); setGithubUser(null); setRepos([]); }}
                className="text-gray-600 hover:text-gray-400 text-xs ml-1"
              >
                Sign out
              </button>
            </div>
          ) : (
            <a
              href={`${API}/auth/github`}
              className="flex items-center gap-2 bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              <span>Connect GitHub</span>
            </a>
          )}
        </div>
      </div>

      {/* ── SNIPPET MODE ── */}
      {mode === "snippet" && (!githubUser || !anthropicKey) && (
        <div className="flex flex-1 items-center justify-center">
          <div className="text-center flex flex-col items-center gap-6 max-w-sm">
            <div className="flex flex-col items-center gap-2">
              <span className={`text-2xl ${githubUser ? "opacity-30" : ""}`}>①</span>
              <p className={`text-sm font-semibold ${githubUser ? "text-gray-600 line-through" : "text-gray-200"}`}>Connect GitHub</p>
              {!githubUser && (
                <a
                  href={`${API}/auth/github`}
                  className="mt-1 bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-200 text-sm font-medium px-5 py-2 rounded-lg transition-colors"
                >
                  Connect GitHub
                </a>
              )}
            </div>
            <div className="flex flex-col items-center gap-2">
              <span className={`text-2xl ${anthropicKey ? "opacity-30" : ""}`}>②</span>
              <p className={`text-sm font-semibold ${anthropicKey ? "text-gray-600 line-through" : "text-gray-200"}`}>Add your Anthropic API key</p>
              {!anthropicKey && (
                <button
                  onClick={() => setShowKeyPanel(true)}
                  className="mt-1 bg-yellow-900/40 hover:bg-yellow-900/60 border border-yellow-700 text-yellow-300 text-sm font-medium px-5 py-2 rounded-lg transition-colors"
                >
                  Add API Key
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {mode === "snippet" && githubUser && anthropicKey && (
        <div className="flex flex-1 overflow-hidden">

          {/* Left — Input */}
          <div className="w-1/2 border-r border-gray-800 p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-widest text-gray-500">Input</span>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="bg-gray-800 text-gray-200 text-sm rounded-lg px-3 py-2 border border-gray-700 focus:outline-none focus:border-blue-500 cursor-pointer"
              >
                <option value="python">Python</option>
                <option value="javascript">JavaScript</option>
                <option value="typescript">TypeScript</option>
                <option value="java">Java</option>
                <option value="cpp">C++</option>
                <option value="go">Go</option>
                <option value="rust">Rust</option>
              </select>
            </div>

            <textarea
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Paste your code here..."
              className="flex-1 bg-gray-900 text-gray-100 font-mono text-sm leading-6 rounded-xl p-5 border border-gray-800 focus:outline-none focus:border-blue-600 resize-none placeholder-gray-700"
            />

            <div className="flex items-center justify-between">
              <span className={`text-xs ${code.length > 4500 ? "text-red-400" : "text-gray-600"}`}>
                {code.length} / 5000 chars
              </span>
              <button
                onClick={handleSubmit}
                disabled={loading || code.length === 0}
                className="bg-blue-600 hover:bg-blue-500 disabled:bg-gray-800 disabled:text-gray-600 text-white font-semibold px-8 py-2.5 rounded-lg transition-all duration-200 text-sm"
              >
                {loading ? "Analyzing..." : "Review →"}
              </button>
            </div>

            {error && (
              <div className="bg-red-900/20 border border-red-800 rounded-xl p-4">
                <p className="text-red-400 text-sm">{error}</p>
              </div>
            )}
          </div>

          {/* Right — Results */}
          <div className="w-1/2 overflow-y-auto p-6 flex flex-col gap-4">
            {!result && !loading && (
              <div className="h-full flex items-center justify-center">
                <p className="text-gray-700 text-sm">Paste your code on the left and hit Review</p>
              </div>
            )}
            {loading && (
              <div className="h-full flex flex-col items-center justify-center gap-4">
                <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-400 text-sm">Analyzing your code...</p>
              </div>
            )}
            {result && (
              <>
                <div className="bg-gray-900 rounded-xl border border-gray-700 p-6">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm font-semibold uppercase tracking-widest text-gray-400">Production Score</span>
                    <span className={`text-5xl font-extrabold ${result.score >= 80 ? "text-green-300" : result.score >= 60 ? "text-yellow-300" : "text-red-300"}`}>
                      {result.score}<span className="text-gray-600 text-xl">/100</span>
                    </span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-3 mb-4">
                    <div
                      className={`h-3 rounded-full transition-all duration-700 ${result.score >= 80 ? "bg-green-400" : result.score >= 60 ? "bg-yellow-400" : "bg-red-400"}`}
                      style={{ width: `${result.score}%` }}
                    />
                  </div>
                  <p className="text-gray-200 text-base leading-7 whitespace-pre-wrap">
                    {showScoreDetails ? normalizeAiText(result.score_reasoning) : normalizeAiText(result.score_reasoning).slice(0, 220) + "..."}
                  </p>
                  <button
                    onClick={() => setShowScoreDetails((p) => !p)}
                    className="mt-3 text-xs font-semibold uppercase tracking-wider text-blue-400 hover:text-blue-300"
                  >
                    {showScoreDetails ? "Hide reasoning" : "Show full reasoning"}
                  </button>
                </div>

                <Section title="What Your Code Does" color="gray" defaultOpen={true}>
                  {normalizeAiText(result.explanation)}
                </Section>
                <Section title="Bugs & Vulnerabilities" color="red">
                  {normalizeAiText(result.bugs)}
                </Section>
                <Section title="Suggestions" color="blue">
                  {normalizeAiText(result.suggestions)}
                </Section>
                <Section title="Complexity Analysis" color="purple">
                  {normalizeAiText(result.complexity)}
                </Section>
                <Section title="Security" color="yellow">
                  {normalizeAiText(result.security)}
                </Section>
                {result.cached && (
                  <p className="text-center text-gray-700 text-xs py-2">Retrieved from cache — no API tokens used</p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── REPO MODE ── */}
      {mode === "repo" && (
        <div className="flex flex-1 overflow-hidden">

          {/* Left — Repo list OR file tree */}
          <div className="w-64 border-r border-gray-800 flex flex-col overflow-hidden">

            {!githubToken ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center gap-4">
                <p className="text-gray-500 text-sm">Connect your GitHub account to explore repos</p>
                <a
                  href={`${API}/auth/github`}
                  className="bg-gray-800 hover:bg-gray-700 border border-gray-600 text-gray-200 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  Connect GitHub
                </a>
              </div>
            ) : selectedRepo ? (
              <>
                {/* Back button + repo name */}
                <div className="p-3 border-b border-gray-800 flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => {
                      setSelectedRepo(null);
                      setRepoTree([]);
                      setSelectedFile(null);
                      setFileContent("");
                      setRepoResult(null);
                      setRepoSummary(null);
                      setReadmeContent("");
                    }}
                    className="flex items-center gap-1.5 text-gray-400 hover:text-gray-200 text-xs font-medium transition-colors"
                  >
                    <span>←</span> All repos
                  </button>
                </div>
                <div className="px-4 py-2 border-b border-gray-800 shrink-0">
                  <p className="text-sm text-gray-200 font-semibold truncate">{selectedRepo.name}</p>
                  {selectedRepo.language && (
                    <p className="text-xs text-gray-500 mt-0.5">{selectedRepo.language}</p>
                  )}
                </div>

                {/* File tree */}
                <div className="overflow-y-auto flex-1 p-2">
                  {repoTree.length === 0 ? (
                    <div className="flex items-center justify-center p-8">
                      <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : (
                    <FileTree
                      tree={repoTree}
                      onSelectFile={handleSelectFile}
                      selectedPath={selectedFile?.path}
                    />
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="p-4 border-b border-gray-800 shrink-0">
                  <p className="text-xs font-semibold uppercase tracking-widest text-gray-500">Your Repos</p>
                </div>
                <div className="overflow-y-auto flex-1">
                  {repoLoading && (
                    <div className="flex items-center justify-center p-8">
                      <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                  )}
                  {repos.map((repo) => (
                    <button
                      key={repo.id}
                      onClick={() => handleSelectRepo(repo)}
                      className="w-full text-left px-4 py-3 border-b border-gray-800/50 hover:bg-gray-800 transition-colors"
                    >
                      <p className="text-sm text-gray-200 font-medium truncate">{repo.name}</p>
                      {repo.language && (
                        <p className="text-xs text-gray-500 mt-0.5">{repo.language}</p>
                      )}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Middle — File content */}
          <div className="flex-1 border-r border-gray-800 flex flex-col overflow-hidden">
            {!selectedFile ? (
              readmeContent ? (
                <>
                  <div className="px-5 py-3 border-b border-gray-800 flex items-center justify-between">
                    <span className="text-xs text-gray-500 font-mono">README.md</span>
                    {selectedRepo && (
                      <button
                        onClick={handleExplainRepo}
                        disabled={summaryLoading}
                        className="bg-purple-700 hover:bg-purple-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors"
                      >
                        {summaryLoading ? "Analyzing..." : "Analyze Repo →"}
                      </button>
                    )}
                  </div>
                  <pre className="flex-1 overflow-auto p-5 text-gray-300 font-mono text-xs leading-6 whitespace-pre-wrap">
                    {readmeContent}
                  </pre>
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                  <p className="text-gray-700 text-sm">
                    {selectedRepo ? "Select a file to analyze it" : "Select a repo from the left"}
                  </p>
                  {selectedRepo && (
                    <button
                      onClick={handleExplainRepo}
                      disabled={summaryLoading}
                      className="bg-purple-700 hover:bg-purple-600 disabled:bg-gray-800 disabled:text-gray-600 text-white text-sm font-semibold px-5 py-2 rounded-lg transition-colors"
                    >
                      {summaryLoading ? "Analyzing..." : "Analyze Repo →"}
                    </button>
                  )}
                </div>
              )
            ) : (
              <>
                <div className="px-5 py-3 border-b border-gray-800 flex items-center gap-2">
                  <span className="text-xs text-gray-500 font-mono">{selectedFile.path}</span>
                  {fileLoading && (
                    <div className="w-4 h-4 border border-blue-500 border-t-transparent rounded-full animate-spin ml-2" />
                  )}
                </div>
                <pre className="flex-1 overflow-auto p-5 text-gray-300 font-mono text-xs leading-6">
                  {fileContent}
                </pre>
              </>
            )}
          </div>

          {/* Right — AI Analysis */}
          <div className="w-96 overflow-y-auto p-5 flex flex-col gap-4">
            {/* Repo summary (shown when no file selected) */}
            {!selectedFile && !summaryLoading && repoSummary && !repoSummary.error && (
              <>
                <Section title="What This Repo Does" color="gray" defaultOpen={true}>
                  {normalizeAiText(repoSummary.summary)}
                </Section>
                <Section title="Architecture" color="blue" defaultOpen={true}>
                  {normalizeAiText(repoSummary.architecture)}
                </Section>
                <Section title="Tech Stack" color="purple" defaultOpen={true}>
                  {normalizeAiText(repoSummary.tech_stack)}
                </Section>
                <Section title="Entry Points" color="yellow" defaultOpen={true}>
                  {normalizeAiText(repoSummary.entry_points)}
                </Section>
              </>
            )}

            {!selectedFile && !summaryLoading && repoSummary?.error && (
              <p className="text-red-400 text-sm text-center">{repoSummary.error}</p>
            )}

            {!selectedFile && !summaryLoading && !repoSummary && (
              <div className="flex-1 flex items-center justify-center h-full">
                <p className="text-gray-700 text-sm text-center">
                  {selectedRepo ? 'Click "Analyze Repo →" to see architecture analysis, or select a file' : "Select a repo from the left"}
                </p>
              </div>
            )}

            {summaryLoading && (
              <div className="flex flex-col items-center justify-center gap-4 h-full">
                <div className="w-10 h-10 border-2 border-purple-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-400 text-sm">Analyzing repo architecture...</p>
              </div>
            )}

            {fileLoading && (
              <div className="flex flex-col items-center justify-center gap-4 h-full">
                <div className="w-10 h-10 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-gray-400 text-sm">Analyzing file...</p>
              </div>
            )}

            {repoResult && selectedFile && !fileLoading && (
              repoResult.error || !repoResult.score ? (
                <div className="bg-red-900/20 border border-red-800 rounded-xl p-4">
                  <p className="text-red-400 text-sm">{repoResult.error || repoResult.message || "Analysis failed. You may have hit the rate limit (10/hour)."}</p>
                </div>
              ) : (
              <>
                <div className="bg-gray-900 rounded-xl border border-gray-700 p-5">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-semibold uppercase tracking-widest text-gray-400">Score</span>
                    <span className={`text-3xl font-bold ${repoResult.score >= 80 ? "text-green-300" : repoResult.score >= 60 ? "text-yellow-300" : "text-red-300"}`}>
                      {repoResult.score}<span className="text-gray-600 text-base">/100</span>
                    </span>
                  </div>
                  <div className="w-full bg-gray-800 rounded-full h-2 mb-3">
                    <div
                      className={`h-2 rounded-full ${repoResult.score >= 80 ? "bg-green-400" : repoResult.score >= 60 ? "bg-yellow-400" : "bg-red-400"}`}
                      style={{ width: `${repoResult.score}%` }}
                    />
                  </div>
                </div>

                <Section title="What This File Does" color="gray" defaultOpen={true}>
                  {normalizeAiText(repoResult.explanation)}
                </Section>
                <Section title="Bugs & Vulnerabilities" color="red">
                  {normalizeAiText(repoResult.bugs)}
                </Section>
                <Section title="Suggestions" color="blue">
                  {normalizeAiText(repoResult.suggestions)}
                </Section>
                <Section title="Security" color="yellow">
                  {normalizeAiText(repoResult.security)}
                </Section>
              </>
              )
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;