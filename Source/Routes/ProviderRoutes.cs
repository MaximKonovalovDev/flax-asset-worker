using System;
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
    public static class ProviderRoutes
    {
        public static Task<JObject> HandleListAsync()
        {
            var result = ProviderRegistry.Instance.ListProviders();
            result["success"] = true;
            return Task.FromResult(result);
        }

        /// <summary>
        /// v1.12.s73 — manifest-stats: aggregate on-disk R1A manifests
        /// via subprocess to `python -m assetboy.cli pack manifest-stats --json`.
        /// Returns: manifests_scanned, sources_seen, total_downloaded/skipped/
        /// failed/bytes, by_source breakdown.
        /// </summary>
        public static async Task<JObject> HandleManifestStatsAsync()
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "-m assetboy.cli pack manifest-stats --json",
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
                if (!proc.WaitForExit(20000))
                {
                    try { proc.Kill(); }
                    catch (Exception ex) when (!proc.HasExited)
                    {
                        Log.Warning($"Failed to kill process {proc.Id}: {ex.Message}");
                    }
                    catch (Exception ex) { /* logged by caller */ }
                    return ErrorResult("timeout: pack manifest-stats took > 20s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                // Note: pack manifest-stats exits 1 when --root doesn't exist;
                // that's a structural failure, not "no manifests yet". We propagate
                // the JSON error envelope when present.
                JObject parsed;
                try
                {
                    parsed = JObject.Parse(stdout);
                }
                catch
                {
                    return ErrorResult($"pack_manifest_stats_unparseable: exit={proc.ExitCode} stderr={stderr}");
                }
                parsed["success"] = proc.ExitCode == 0;
                return parsed;
            }
            catch (Exception exc)
            {
                return ErrorResult($"manifest_stats_crashed: {exc.Message}");
            }
        }

        /// <summary>
        /// v1.11.s48 — list gen sub-app providers (R1A + ComfyUI + sd) via
        /// subprocess to `python -m assetboy.cli gen list-providers --json`.
        /// Returns the same shape as the CLI catalog: providers[] + aggregate
        /// counts (no_key_count, key_required_count, key_set_count, etc).
        /// </summary>
        public static async Task<JObject> HandleListGenAsync()
        {
            try
            {
                var psi = new ProcessStartInfo
                {
                    FileName = "python",
                    Arguments = "-m assetboy.cli gen list-providers --json",
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
                    try { proc.Kill(); }
                    catch (Exception ex) when (!proc.HasExited)
                    {
                        Log.Warning($"Failed to kill process {proc.Id}: {ex.Message}");
                    }
                    catch (Exception ex) { /* logged by caller */ }
                    return ErrorResult("timeout: gen list-providers took > 15s");
                }
                var stdout = await stdoutTask;
                var stderr = await stderrTask;
                if (proc.ExitCode != 0)
                {
                    return ErrorResult($"gen_list_providers_failed: exit={proc.ExitCode} stderr={stderr}");
                }
                var parsed = JObject.Parse(stdout);
                parsed["success"] = true;
                return parsed;
            }
            catch (Exception exc)
            {
                return ErrorResult($"gen_list_providers_crashed: {exc.Message}");
            }
        }

        public static async Task<JObject> HandleDownloadAsync(string path, HttpListenerContext ctx)
        {
            // Parse provider ID from path: /api/v1/providers/{id}/download
            var segments = path.Trim('/').Split('/');
            if (segments.Length < 5)
                return ErrorResult("Invalid path. Expected: /api/v1/providers/{id}/download");

            var providerId = segments[3];
            var provider = ProviderRegistry.Instance.GetProvider(providerId);
            if (provider == null)
                return ErrorResult($"Provider '{providerId}' not found");

            // Read request body
            var body = await new StreamReader(ctx.Request.InputStream).ReadToEndAsync();
            var req = JObject.Parse(body ?? "{}");
            var assetId = req["asset_id"]?.ToString();
            if (string.IsNullOrWhiteSpace(assetId))
                return ErrorResult("'asset_id' is required");

            var config = ProviderRegistry.Instance.GetConfig(providerId);
            var result = await provider.DownloadAsync(assetId, config);

            var response = result.ToJson();
            response["success"] = result.Success;
            response["provider"] = providerId;
            return response;
        }
        
        public static Task<JObject> HandleSearchAsync(string path, HttpListenerContext ctx)
        {
            return Task.FromResult(ErrorResult("not_implemented: Provider search not yet implemented"));
        }

        private static JObject ErrorResult(string error)
        {
            return new JObject { ["success"] = false, ["error"] = error };
        }
    }
}
