using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Routes
{
    public static class LibraryRoutes
    {
        private static readonly string LibraryFile;

        static LibraryRoutes()
        {
            var root = Path.Combine(Globals.ProjectFolder, "Library");
            Directory.CreateDirectory(root);
            LibraryFile = Path.Combine(root, "asset_library.json");
        }

        public static async Task<JObject> HandleSearchAsync(HttpListenerContext ctx)
        {
            var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
            var req = JObject.Parse(body ?? "{}");
            var query = req["query"]?.ToString() ?? "";

            var library = LoadLibrary();
            var results = new JArray();
            foreach (var asset in library)
            {
                var name = asset["name"]?.ToString() ?? "";
                var cat = asset["category"]?.ToString() ?? "";
                if (string.IsNullOrEmpty(query) ||
                    name.Contains(query, System.StringComparison.OrdinalIgnoreCase) ||
                    cat.Contains(query, System.StringComparison.OrdinalIgnoreCase))
                {
                    results.Add(asset);
                }
            }

            return new JObject { ["success"] = true, ["results"] = results, ["count"] = results.Count };
        }

        public static async Task<JObject> HandleInstallAsync(HttpListenerContext ctx)
        {
            var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
            var req = JObject.Parse(body ?? "{}");

            var assetId = req["asset_id"]?.ToString();
            var providerId = req["provider"]?.ToString();
            var category = req["category"]?.ToString() ?? "unknown";
            var name = req["name"]?.ToString() ?? assetId;

            if (string.IsNullOrWhiteSpace(assetId))
                return Error("'asset_id' is required");

            if (string.IsNullOrWhiteSpace(providerId))
                return Error("'provider' is required");

            var provider = Providers.ProviderRegistry.Instance.GetProvider(providerId);
            if (provider == null)
                return Error($"Provider '{providerId}' not found");

            var config = Providers.ProviderRegistry.Instance.GetConfig(providerId);
            var result = await provider.DownloadAsync(assetId, config);

            if (!result.Success)
                return new JObject { ["success"] = false, ["error"] = result.Error };

            // Record in library
            var library = LoadLibrary();
            var entry = new JObject
            {
                ["id"] = assetId,
                ["name"] = name,
                ["provider"] = providerId,
                ["category"] = category,
                ["local_path"] = result.LocalPath,
                ["format"] = result.Format,
                ["file_size_bytes"] = result.FileSizeBytes,
                ["sha256"] = result.Sha256,
                ["installed_at"] = System.DateTime.UtcNow.ToString("O")
            };
            library.Add(entry);
            SaveLibrary(library);

            return new JObject
            {
                ["success"] = true,
                ["asset"] = entry,
                ["message"] = $"'{name}' installed from {providerId}"
            };
        }

        public static JObject HandleReady()
        {
            var library = LoadLibrary();
            return new JObject
            {
                ["success"] = true,
                ["ready_assets"] = new JArray(library),
                ["count"] = library.Count
            };
        }

        /// <summary>
        /// Path B v1.6.s2 (2026-05-11): single-asset metadata lookup.
        ///
        /// GET /api/v1/library/asset/{asset_id}
        ///   Returns: { success: true, asset: {...} }
        ///   404:     { success: false, error: "asset_not_found", asset_id: ... }
        ///
        /// Linear scan of the library JSON. Library is small (~hundreds of
        /// entries max for any real game) so O(N) is fine; if it ever grows
        /// past ~10k entries, switch to a keyed index.
        /// </summary>
        public static JObject HandleGetAsset(string assetId)
        {
            if (string.IsNullOrWhiteSpace(assetId))
            {
                return new JObject
                {
                    ["success"] = false,
                    ["error"] = "missing_asset_id",
                };
            }

            var library = LoadLibrary();
            foreach (var asset in library)
            {
                var id = asset["id"]?.ToString() ?? "";
                if (string.Equals(id, assetId, System.StringComparison.OrdinalIgnoreCase))
                {
                    return new JObject
                    {
                        ["success"] = true,
                        ["asset"] = asset,
                    };
                }
            }

            return new JObject
            {
                ["success"] = false,
                ["error"] = "asset_not_found",
                ["asset_id"] = assetId,
            };
        }

        private static List<JObject> LoadLibrary()
        {
            if (!File.Exists(LibraryFile)) return new List<JObject>();
            var json = File.ReadAllText(LibraryFile);
            return JsonConvert.DeserializeObject<List<JObject>>(json) ?? new List<JObject>();
        }

        private static void SaveLibrary(List<JObject> library)
        {
            File.WriteAllText(LibraryFile, JsonConvert.SerializeObject(library, Formatting.Indented));
        }

        /// <summary>
        /// v1.12.s76 / v1.13.s82 — R1A operator readiness dashboard via subprocess.
        /// Request body may include {"check_live": true} to add live API probes
        /// (adds ~2-5s to wall time; concurrent across 10 providers).
        /// </summary>
        public static async Task<JObject> HandleR1aStatusAsync(HttpListenerContext ctx = null)
        {
            try
            {
                bool checkLive = false;
                if (ctx != null && ctx.Request != null && ctx.Request.HasEntityBody)
                {
                    try
                    {
                        var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
                        if (!string.IsNullOrWhiteSpace(body))
                        {
                            var req = JObject.Parse(body);
                            checkLive = req["check_live"]?.Value<bool>() ?? false;
                        }
                    }
                    catch { /* ignore malformed body; default check_live=false */ }
                }

                var args = checkLive
                    ? "-m assetboy.cli library r1a-status --check-live --json"
                    : "-m assetboy.cli library r1a-status --json";
                var timeoutMs = checkLive ? 30000 : 15000;

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = args,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                var proc = new Process { StartInfo = psi };
                proc.Start();
                var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                var stderrTask = proc.StandardError.ReadToEndAsync();
                if (!proc.WaitForExit(timeoutMs))
                {
                    try { proc.Kill(); } catch { }
                    return Error($"timeout: library r1a-status took > {timeoutMs/1000}s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                {
                    return Error($"r1a_status_failed: exit={proc.ExitCode} stderr={stderr}");
                }
                JObject parsed;
                try { parsed = JObject.Parse(stdout); }
                catch (Exception jx) { return Error($"r1a_status_unparseable: {jx.Message}"); }
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return Error($"r1a_status_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.14.s106 — unified library/provider health report.
        /// Combines C# ProviderRegistry counts + Python r1a-status (no live
        /// probes by default; pass {"check_live": true} to enable them).
        /// </summary>
        public static async Task<JObject> HandleHealthAsync(HttpListenerContext ctx)
        {
            try
            {
                bool checkLive = false;
                if (ctx != null && ctx.Request != null && ctx.Request.HasEntityBody)
                {
                    try
                    {
                        var bodyStr = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
                        if (!string.IsNullOrWhiteSpace(bodyStr))
                        {
                            var req = JObject.Parse(bodyStr);
                            checkLive = req["check_live"]?.Value<bool>() ?? false;
                        }
                    }
                    catch { /* ignore malformed body */ }
                }

                // C# native provider registry side.
                JObject csNative;
                try
                {
                    csNative = ProviderRegistry.Instance.ListProviders();
                    csNative["count"] = ProviderRegistry.Instance.Count;
                }
                catch (Exception csExc)
                {
                    csNative = new JObject { ["error"] = $"csharp_registry_failed: {csExc.Message}" };
                }

                // Python R1A side via subprocess.
                var args = checkLive
                    ? "-m assetboy.cli library r1a-status --check-live --json"
                    : "-m assetboy.cli library r1a-status --json";
                var timeoutMs = checkLive ? 30000 : 15000;
                JObject r1a;
                try
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = "python",
                        Arguments = args,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        StandardOutputEncoding = Encoding.UTF8,
                        StandardErrorEncoding = Encoding.UTF8,
                    };
                    var proc = new Process { StartInfo = psi };
                    proc.Start();
                    var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                    var stderrTask = proc.StandardError.ReadToEndAsync();
                    if (!proc.WaitForExit(timeoutMs))
                    {
                        try { proc.Kill(); } catch { }
                        r1a = new JObject { ["error"] = $"python_r1a_timeout_{timeoutMs / 1000}s" };
                    }
                    else
                    {
                        var stdout = await stdoutTask;
                        var stderr = await stderrTask;
                        if (proc.ExitCode != 0)
                        {
                            r1a = new JObject
                            {
                                ["error"] = $"python_r1a_failed: exit={proc.ExitCode}",
                                ["stderr"] = stderr,
                            };
                        }
                        else
                        {
                            try { r1a = JObject.Parse(stdout); }
                            catch (Exception jx)
                            {
                                r1a = new JObject { ["error"] = $"python_r1a_unparseable: {jx.Message}" };
                            }
                        }
                    }
                }
                catch (Exception pyExc)
                {
                    r1a = new JObject { ["error"] = $"python_r1a_crashed: {pyExc.Message}" };
                }

                return new JObject
                {
                    ["success"] = true,
                    ["checked_live"] = checkLive,
                    ["csharp_native_providers"] = csNative,
                    ["python_r1a"] = r1a,
                };
            }
            catch (Exception exc)
            {
                return Error($"health_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.13.s96 — scout-by-license via subprocess. Body shape:
        ///   {"license": "cc0", "query": "stone wall", "count": 2, "dry_run": true}
        /// </summary>
        public static async Task<JObject> HandleScoutByLicenseAsync(HttpListenerContext ctx)
        {
            try
            {
                var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
                JObject req;
                try { req = JObject.Parse(body ?? "{}"); }
                catch (Exception jx) { return Error($"body_unparseable: {jx.Message}"); }

                var license = req["license"]?.ToString() ?? "";
                var query = req["query"]?.ToString() ?? "";
                var count = req["count"]?.Value<int>() ?? 2;
                var dryRun = req["dry_run"]?.Value<bool>() ?? true;

                if (string.IsNullOrWhiteSpace(license))
                    return Error("missing_required_field: license");
                if (string.IsNullOrWhiteSpace(query))
                    return Error("missing_required_field: query");

                var args = $"-m assetboy.cli gen scout-by-license --license \"{license}\" --query \"{query}\" --count {count} --json";
                if (dryRun) args += " --dry-run";

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = args,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                var proc = new Process { StartInfo = psi };
                proc.Start();
                var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                var stderrTask = proc.StandardError.ReadToEndAsync();
                if (!proc.WaitForExit(30000))
                {
                    try { proc.Kill(); } catch { }
                    return Error("timeout: scout-by-license took > 30s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                    return Error($"scout_by_license_failed: exit={proc.ExitCode} stderr={stderr}");
                JObject parsed;
                try { parsed = JObject.Parse(stdout); }
                catch (Exception jx) { return Error($"scout_by_license_unparseable: {jx.Message}"); }
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return Error($"scout_by_license_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.24.s163 — gen history-tail via subprocess. Query params:
        ///   ?last=N (default 10, 0=all)
        ///   ?kind=all_no_key|all_key|<empty>
        /// </summary>
        public static async Task<JObject> HandleHistoryTailAsync(HttpListenerContext ctx)
        {
            try
            {
                var last = ctx.Request.QueryString["last"];
                var kind = ctx.Request.QueryString["kind"] ?? "";
                int lastN = 10;
                if (!string.IsNullOrWhiteSpace(last))
                {
                    if (!int.TryParse(last, out lastN) || lastN < 0)
                        return Error($"bad_last: '{last}' (expected non-negative int)");
                }

                var args = $"-m assetboy.cli gen history-tail --last {lastN} --json";
                if (!string.IsNullOrWhiteSpace(kind))
                    args += $" --kind {kind}";

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = args,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                var proc = new Process { StartInfo = psi };
                proc.Start();
                var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                var stderrTask = proc.StandardError.ReadToEndAsync();
                if (!proc.WaitForExit(15000))
                {
                    try { proc.Kill(); } catch { }
                    return Error("timeout: history-tail took > 15s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                    return Error($"history_tail_failed: exit={proc.ExitCode} stderr={stderr}");
                JObject parsed;
                try { parsed = JObject.Parse(stdout); }
                catch (Exception jx) { return Error($"history_tail_unparseable: {jx.Message}"); }
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return Error($"history_tail_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.63.s291: GET /api/v1/library/recipe-graph
        /// Wraps `pack list-recipes --graph --json` to surface the
        /// cross-recipe relation graph (built from recipe.related_recipes).
        /// Query params:
        ///   ?recipes_root=&lt;path&gt; (optional override)
        /// Response: full graph dict with out_edges, in_edges, dangling,
        /// orphans, is_acyclic, topo_order, entry_points, leaves, max_depth.
        /// </summary>
        public static async Task<JObject> HandleRecipeGraphAsync(HttpListenerContext ctx)
        {
            try
            {
                var recipesRoot = ctx.Request.QueryString["recipes_root"] ?? "";

                var args = "-m assetboy.cli pack list-recipes --graph";
                if (!string.IsNullOrWhiteSpace(recipesRoot))
                    args += $" --recipes-root \"{recipesRoot}\"";

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = args,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                var proc = new Process { StartInfo = psi };
                proc.Start();
                var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                var stderrTask = proc.StandardError.ReadToEndAsync();
                if (!proc.WaitForExit(15000))
                {
                    try { proc.Kill(); } catch { }
                    return Error("timeout: recipe-graph took > 15s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                    return Error($"recipe_graph_failed: exit={proc.ExitCode} stderr={stderr}");
                JObject parsed;
                try { parsed = JObject.Parse(stdout); }
                catch (Exception jx) { return Error($"recipe_graph_unparseable: {jx.Message}"); }
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return Error($"recipe_graph_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.64.s294: GET /api/v1/library/recipe-plan
        /// Wraps `pack list-recipes --plan --json` to surface the
        /// pipeline execution plan (topo order + depth + depends_on).
        /// Query params:
        ///   ?recipes_root=&lt;path&gt; (optional)
        ///   ?batches=true (emit batches instead of flat plan)
        /// </summary>
        public static async Task<JObject> HandleRecipePlanAsync(HttpListenerContext ctx)
        {
            try
            {
                var recipesRoot = ctx.Request.QueryString["recipes_root"] ?? "";
                var batches = ctx.Request.QueryString["batches"] ?? "";

                var args = "-m assetboy.cli pack list-recipes --plan --json";
                if (!string.IsNullOrWhiteSpace(recipesRoot))
                    args += $" --recipes-root \"{recipesRoot}\"";
                if (batches.ToLowerInvariant() == "true")
                    args += " --batches";

                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = args,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    StandardOutputEncoding = Encoding.UTF8,
                    StandardErrorEncoding = Encoding.UTF8,
                };
                var proc = new Process { StartInfo = psi };
                proc.Start();
                var stdoutTask = proc.StandardOutput.ReadToEndAsync();
                var stderrTask = proc.StandardError.ReadToEndAsync();
                if (!proc.WaitForExit(15000))
                {
                    try { proc.Kill(); } catch { }
                    return Error("timeout: recipe-plan took > 15s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                    return Error($"recipe_plan_failed: exit={proc.ExitCode} stderr={stderr}");
                JObject parsed;
                try { parsed = JObject.Parse(stdout); }
                catch (Exception jx) { return Error($"recipe_plan_unparseable: {jx.Message}"); }
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return Error($"recipe_plan_crashed: {exc.Message}");
            }
        }

        private static JObject Error(string msg) => new JObject { ["success"] = false, ["error"] = msg };
    }
}
