using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Core
{
    public class WorkerHttpServer
    {
        private readonly WorkerConfig _config;
        private HttpListener _listener;
        private bool _running;

        public WorkerHttpServer(WorkerConfig config)
        {
            _config = config;
        }

        public void Start()
        {
            try
            {
                _listener = new HttpListener();
                _listener.Prefixes.Add($"http://localhost:{_config.Port}/");
                _listener.Start();
                _running = true;
                Task.Run(() => ListenLoop());
                Debug.Log($"[AssetWorker] HTTP server listening on http://localhost:{_config.Port}");
            }
            catch (Exception ex)
            {
                Debug.LogError($"[AssetWorker] Failed to start HTTP server: {ex.Message}");
            }
        }

        public void Stop()
        {
            _running = false;
            try { _listener?.Stop(); } catch { }
            try { _listener?.Close(); } catch { }
            Debug.Log("[AssetWorker] HTTP server stopped");
        }

        private async void ListenLoop()
        {
            while (_running)
            {
                try
                {
                    var ctx = await _listener.GetContextAsync();
                    _ = HandleRequestAsync(ctx);
                }
                catch (Exception ex) when (!_running)
                {
                    break; // Server stopped
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[AssetWorker] Request error: {ex.Message}");
                }
            }
        }

        private async Task HandleRequestAsync(HttpListenerContext ctx)
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            var path = ctx.Request.Url.AbsolutePath.ToLowerInvariant();
            var method = ctx.Request.HttpMethod;

            try
            {
                JObject result;

                if (path == "/api/v1/health" && method == "GET")
                {
                    var pythonAlive = await PythonWorkerClient.IsAliveAsync();
                    result = new JObject
                    {
                        ["status"] = "ok",
                        ["version"] = "1.0.0",
                        ["providers"] = ProviderRegistry.Instance.Count,
                        ["python_worker"] = pythonAlive ? "connected" : "offline",
                        ["uptime_ms"] = sw.ElapsedMilliseconds
                    };
                }
                else if (path == "/api/v1/providers/list" && method == "POST")
                {
                    result = await ProviderRoutes.HandleListAsync();
                }
                else if (path == "/api/v1/providers/list-gen" && method == "POST")
                {
                    // v1.11.s48 — enumerate Python gen sub-app providers (R1A catalog).
                    result = await ProviderRoutes.HandleListGenAsync();
                }
                else if (path == "/api/v1/manifest/stats" && method == "POST")
                {
                    // v1.12.s73 — aggregate R1A manifests on disk.
                    result = await ProviderRoutes.HandleManifestStatsAsync();
                }
                else if (path.StartsWith("/api/v1/providers/") && path.Contains("/download"))
                {
                    result = await ProviderRoutes.HandleDownloadAsync(path, ctx);
                }
                else if (path == "/api/v1/lanes/list" && method == "POST")
                {
                    result = LaneRoutes.HandleList();
                }
                else if (path.StartsWith("/api/v1/lanes/") && path.Contains("/execute"))
                {
                    result = await LaneRoutes.HandleExecuteAsync(path, ctx);
                }
                else if (path == "/api/v1/library/search" && method == "POST")
                {
                    result = await LibraryRoutes.HandleSearchAsync(ctx);
                }
                else if (path == "/api/v1/library/install" && method == "POST")
                {
                    result = await LibraryRoutes.HandleInstallAsync(ctx);
                }
                else if (path == "/api/v1/library/ready" && method == "POST")
                {
                    result = LibraryRoutes.HandleReady();
                }
                else if (path == "/api/v1/library/r1a-status" && method == "POST")
                {
                    // v1.12.s76 / v1.13.s82 — R1A operator readiness dashboard.
                    // Body: {"check_live": true} adds live API probes.
                    result = await LibraryRoutes.HandleR1aStatusAsync(ctx);
                }
                else if (path == "/api/v1/library/scout-by-license" && method == "POST")
                {
                    // v1.13.s96 — fan out across license-filtered providers.
                    result = await LibraryRoutes.HandleScoutByLicenseAsync(ctx);
                }
                else if (path == "/api/v1/library/health" && method == "POST")
                {
                    // v1.14.s106 — unified C# registry + Python R1A health report.
                    // Body: {"check_live": true} adds live API probes.
                    result = await LibraryRoutes.HandleHealthAsync(ctx);
                }
                else if (path.StartsWith("/api/v1/library/asset/") && method == "GET")
                {
                    // v1.6.s2: single-asset metadata lookup
                    var assetId = path.Substring("/api/v1/library/asset/".Length);
                    // Strip trailing slash if present
                    if (assetId.EndsWith("/")) assetId = assetId.Substring(0, assetId.Length - 1);
                    result = LibraryRoutes.HandleGetAsset(assetId);
                    if (result["success"]?.ToObject<bool>() == false &&
                        result["error"]?.ToString() == "asset_not_found")
                    {
                        ctx.Response.StatusCode = 404;
                    }
                }
                else if (path == "/api/v1/recipes/list" && method == "POST")
                {
                    result = await RecipeRoutes.HandleListAsync();
                }
                else if (path == "/api/v1/recipes/run" && method == "POST")
                {
                    result = await RecipeRoutes.HandleRunAsync(ctx);
                }
                else if (path == "/api/v1/packs/run-pack" && method == "POST")
                {
                    // v1.6.s7: single-pack execution from inline YAML body
                    result = await RecipeRoutes.HandleRunPackAsync(ctx);
                }
                else if (path == "/api/v1/packs/audit" && method == "GET")
                {
                    // v1.6.s3: inventory all pack_pipeline ledgers
                    var gameFilter = ctx.Request.QueryString["game"] ?? "";
                    var includeLedgersStr = ctx.Request.QueryString["include_ledgers"] ?? "true";
                    var includeLedgers = !string.Equals(includeLedgersStr, "false",
                        StringComparison.OrdinalIgnoreCase);
                    int maxLedgers = 1000;
                    var maxStr = ctx.Request.QueryString["max"];
                    if (!string.IsNullOrWhiteSpace(maxStr) && int.TryParse(maxStr, out var parsed))
                    {
                        maxLedgers = parsed;
                    }
                    result = await RecipeRoutes.HandleAuditAsync(gameFilter, includeLedgers, maxLedgers);
                }
                else if (path.StartsWith("/api/v1/packs/") && path.EndsWith("/status") && method == "GET")
                {
                    // Parse /api/v1/packs/{pack_id}/status
                    var packId = path.Substring("/api/v1/packs/".Length);
                    packId = packId.Substring(0, packId.Length - "/status".Length);
                    var gameScope = ctx.Request.QueryString["game"] ?? "primitive_tech";
                    result = await RecipeRoutes.HandlePackStatusAsync(packId, gameScope);
                }
                else if (path == "/api/v1/canary/status" && method == "GET")
                {
                    result = await CanaryRoutes.HandleStatusAsync();
                }
                else
                {
                    result = new JObject
                    {
                        ["success"] = false,
                        ["error"] = "Not found",
                        ["path"] = path
                    };
                    ctx.Response.StatusCode = 404;
                }

                var responseBytes = Encoding.UTF8.GetBytes(result.ToString(Formatting.None));
                ctx.Response.ContentType = "application/json";
                ctx.Response.ContentLength64 = responseBytes.Length;
                await ctx.Response.OutputStream.WriteAsync(responseBytes, 0, responseBytes.Length);
            }
            catch (Exception ex)
            {
                var error = new JObject
                {
                    ["success"] = false,
                    ["error"] = ex.Message,
                    ["path"] = path
                };
                var errorBytes = Encoding.UTF8.GetBytes(error.ToString(Formatting.None));
                ctx.Response.StatusCode = 500;
                ctx.Response.ContentType = "application/json";
                ctx.Response.ContentLength64 = errorBytes.Length;
                await ctx.Response.OutputStream.WriteAsync(errorBytes, 0, errorBytes.Length);
            }
            finally
            {
                ctx.Response.Close();
                if (_config.VerboseLogging)
                    Debug.Log($"[AssetWorker] {method} {path} → {ctx.Response.StatusCode} ({sw.ElapsedMilliseconds}ms)");
            }
        }
    }
}
