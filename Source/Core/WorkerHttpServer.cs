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
