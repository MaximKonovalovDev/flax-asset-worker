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

        private static JObject Error(string msg) => new JObject { ["success"] = false, ["error"] = msg };
    }
}
