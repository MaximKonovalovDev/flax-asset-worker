using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Providers
{
    /// <summary>
    /// PolyHaven provider - free CC0 textures, models, and HDRIs.
    /// No authentication required. Uses the public PolyHaven API.
    /// </summary>
    public class PolyHavenProvider : IAssetProvider
    {
        private static readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(120) };
        private const string API_BASE = "https://api.polyhaven.com";

        public string Id => "polyhaven";
        public string Name => "PolyHaven";
        public string Description => "Free CC0 textures, models, and HDRIs. No authentication required.";
        public bool RequiresAuth => false;
        public bool IsFree => true;

        public AssetCategory[] SupportedCategories => new[]
        {
            AssetCategory.Texture,
            AssetCategory.Model,
            AssetCategory.HDR
        };

        public Task<bool> AuthenticateAsync(ProviderConfig config)
        {
            return Task.FromResult(true); // No auth needed
        }

        public async Task<DownloadResult> DownloadAsync(string assetId, ProviderConfig config)
        {
            try
            {
                // Get asset info
                var infoUrl = $"{API_BASE}/info/{assetId}";
                var infoResponse = await _http.GetStringAsync(infoUrl);
                var info = JObject.Parse(infoResponse);

                var assetType = info["type"]?.Value<int>() ?? 0;
                var category = assetType switch
                {
                    0 => AssetCategory.Texture,
                    2 => AssetCategory.Model,
                    1 => AssetCategory.HDR,
                    _ => AssetCategory.Texture
                };

                // Determine download URL based on category
                string downloadUrl;
                string format;
                if (category == AssetCategory.Texture)
                {
                    var resolution = "2k"; // Default
                    downloadUrl = $"{API_BASE}/files/{assetId}";
                    format = ".zip";
                }
                else
                {
                    var fileFormat = category == AssetCategory.Model ? "gltf" : "hdr";
                    var resolution = "1k";
                    downloadUrl = $"{API_BASE}/files/{assetId}";
                    format = category == AssetCategory.Model ? ".gltf" : ".hdr";
                }

                // Get file list
                var filesResponse = await _http.GetStringAsync($"{API_BASE}/files/{assetId}");
                var files = JObject.Parse(filesResponse);

                // Download the first available texture/model/HDR
                var textureFiles = files["blend"]?["blend"]?["8k"]?["blend"]?.ToString();
                var downloadPath = textureFiles;

                if (string.IsNullOrEmpty(downloadPath))
                {
                    return new DownloadResult
                    {
                        Success = false,
                        Error = $"No downloadable files found for asset '{assetId}'"
                    };
                }

                // Download file
                var fileBytes = await _http.GetByteArrayAsync(downloadPath);
                var cacheDir = Path.Combine(Path.GetTempPath(), "FAWCache", "polyhaven");
                Directory.CreateDirectory(cacheDir);

                var localPath = Path.Combine(cacheDir, $"{assetId}{format}");
                await File.WriteAllBytesAsync(localPath, fileBytes);

                // Compute SHA-256
                var sha256 = ComputeSha256(fileBytes);

                return new DownloadResult
                {
                    Success = true,
                    AssetId = assetId,
                    LocalPath = localPath,
                    Category = category,
                    Format = format.TrimStart('.'),
                    FileSizeBytes = fileBytes.Length,
                    Sha256 = sha256,
                    Metadata = new Dictionary<string, string>
                    {
                        ["provider"] = "polyhaven",
                        ["license"] = "CC0",
                        ["name"] = info["name"]?.ToString() ?? assetId
                    }
                };
            }
            catch (Exception ex)
            {
                return new DownloadResult
                {
                    Success = false,
                    Error = ex.Message
                };
            }
        }

        public async Task<List<AssetSearchResult>> SearchAsync(string query, AssetCategory? category = null)
        {
            try
            {
                var url = $"{API_BASE}/assets?type={(category == AssetCategory.Model ? 2 : category == AssetCategory.HDR ? 1 : 0)}";
                var response = await _http.GetStringAsync(url);
                var data = JObject.Parse(response);

                var results = new List<AssetSearchResult>();
                foreach (var prop in data.Properties())
                {
                    var asset = prop.Value as JObject;
                    if (asset == null) continue;

                    var name = asset["name"]?.ToString() ?? prop.Name;
                    if (!string.IsNullOrEmpty(query) && !name.Contains(query, StringComparison.OrdinalIgnoreCase))
                        continue;

                    var thumbnails = asset["thumbnails"] as JObject;
                    var thumbnailUrl = thumbnails?.Properties().FirstOrDefault()?.Value?.ToString();

                    results.Add(new AssetSearchResult
                    {
                        Id = prop.Name,
                        Name = name,
                        Category = category ?? AssetCategory.Texture,
                        Provider = "polyhaven",
                        ThumbnailUrl = thumbnailUrl,
                        Tags = new Dictionary<string, string>
                        {
                            ["license"] = "CC0",
                            ["author"] = asset["author"]?.ToString() ?? ""
                        }
                    });

                    if (results.Count >= 20) break;
                }

                return results;
            }
            catch
            {
                return new List<AssetSearchResult>();
            }
        }

        public Task<bool> ValidateAsync(string localPath)
        {
            return Task.FromResult(File.Exists(localPath));
        }

        private static string ComputeSha256(byte[] data)
        {
            var hash = SHA256.HashData(data);
            return Convert.ToHexStringLower(hash);
        }
    }
}
