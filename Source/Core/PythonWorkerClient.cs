using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Core
{
    /// <summary>
    /// HTTP client that calls the Python AssetBoy worker server (port 8766).
    /// Used for auth-heavy providers (Fab/OAuth, Epic/Playwright, Mixamo/web),
    /// Blender optimization, and AI generation.
    /// </summary>
    public static class PythonWorkerClient
    {
        private static readonly HttpClient _http = new() { Timeout = TimeSpan.FromMinutes(5) };
        private const string DefaultBaseUrl = "http://127.0.0.1:8766";

        public static string BaseUrl { get; set; } = DefaultBaseUrl;

        public static async Task<bool> IsAliveAsync()
        {
            try
            {
                var result = await CallAsync("health", new JObject());
                return result?["status"]?.ToString() == "ok";
            }
            catch
            {
                return false;
            }
        }

        public static async Task<JObject> CallAsync(string route, JObject payload)
        {
            var url = $"{BaseUrl}/{route.TrimStart('/')}";
            var content = new StringContent(payload.ToString(Formatting.None), Encoding.UTF8, "application/json");

            var response = await _http.PostAsync(url, content);
            response.EnsureSuccessStatusCode();

            var body = await response.Content.ReadAsStringAsync();
            return JObject.Parse(body);
        }

        public static async Task<JObject> FabAuthAsync(string email, string password)
        {
            return await CallAsync("fab/auth", new JObject
            {
                ["email"] = email,
                ["password"] = password
            });
        }

        public static async Task<JObject> MixamoDownloadAsync(string animationId, string characterId)
        {
            return await CallAsync("mixamo/download", new JObject
            {
                ["animation_id"] = animationId,
                ["character_id"] = characterId
            });
        }

        public static async Task<JObject> BlenderOptimizeAsync(string inputPath, string outputPath)
        {
            return await CallAsync("blender/optimize", new JObject
            {
                ["input_path"] = inputPath,
                ["output_path"] = outputPath
            });
        }

        public static async Task<JObject> GenerateImageAsync(string prompt, string style = "game_asset")
        {
            return await CallAsync("generate/image", new JObject
            {
                ["prompt"] = prompt,
                ["style"] = style
            });
        }
    }
}
