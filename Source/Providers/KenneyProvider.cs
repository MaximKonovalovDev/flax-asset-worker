using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Security.Cryptography;
using System.Threading.Tasks;
using FlaxEngine;
using Newtonsoft.Json.Linq;

namespace FAW.Providers
{
    /// <summary>
    /// Kenney.nl provider - free CC0 game assets (textures, models, audio, sprites).
    /// No authentication required. Downloads from kenney.nl CDN.
    /// </summary>
    public class KenneyProvider : IAssetProvider
    {
        private static readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(120) };
        private const string ASSETS_URL = "https://kenney.nl/assets";

        public string Id => "kenney";
        public string Name => "Kenney";
        public string Description => "Free CC0 game assets (textures, models, audio, sprites). No authentication.";
        public bool RequiresAuth => false;
        public bool IsFree => true;

        public AssetCategory[] SupportedCategories => new[]
        {
            AssetCategory.Texture,
            AssetCategory.Model,
            AssetCategory.Audio,
            AssetCategory.Sprite,
            AssetCategory.Font
        };

        public Task<bool> AuthenticateAsync(ProviderConfig config)
        {
            return Task.FromResult(true);
        }

        public async Task<DownloadResult> DownloadAsync(string assetId, ProviderConfig config)
        {
            try
            {
                var downloadUrl = $"{ASSETS_URL}/{assetId}/{assetId}.zip";
                var fileBytes = await _http.GetByteArrayAsync(downloadUrl);

                var cacheDir = Path.Combine(Path.GetTempPath(), "FAWCache", "kenney");
                Directory.CreateDirectory(cacheDir);

                var zipPath = Path.Combine(cacheDir, $"{assetId}.zip");
                await File.WriteAllBytesAsync(zipPath, fileBytes);

                // Extract
                var extractDir = Path.Combine(cacheDir, assetId);
                if (Directory.Exists(extractDir))
                    Directory.Delete(extractDir, true);
                ZipFile.ExtractToDirectory(zipPath, extractDir);

                // Find first usable file
                var assetsDir = Path.Combine(extractDir, assetId);
                if (!Directory.Exists(assetsDir))
                    assetsDir = extractDir;

                // Determine category and find best file
                AssetCategory category = AssetCategory.Texture;
                string bestFile = null;

                foreach (var file in Directory.GetFiles(assetsDir, "*.*", SearchOption.AllDirectories))
                {
                    var ext = Path.GetExtension(file).ToLowerInvariant();
                    if (ext == ".png" || ext == ".jpg")
                    {
                        bestFile = file;
                        category = AssetCategory.Texture;
                        break;
                    }
                    else if (ext == ".gltf" || ext == ".glb" || ext == ".obj")
                    {
                        bestFile = file;
                        category = AssetCategory.Model;
                        break;
                    }
                    else if (ext == ".wav" || ext == ".mp3" || ext == ".ogg")
                    {
                        bestFile = file;
                        category = AssetCategory.Audio;
                        break;
                    }
                    else if (bestFile == null)
                    {
                        bestFile = file;
                    }
                }

                if (bestFile == null)
                    return new DownloadResult { Success = false, Error = "No usable files found in archive" };

                var sha256 = ComputeSha256(File.ReadAllBytes(bestFile));
                var fileInfo = new FileInfo(bestFile);

                return new DownloadResult
                {
                    Success = true,
                    AssetId = assetId,
                    LocalPath = bestFile,
                    Category = category,
                    Format = fileInfo.Extension.TrimStart('.'),
                    FileSizeBytes = fileInfo.Length,
                    Sha256 = sha256,
                    Metadata = new Dictionary<string, string>
                    {
                        ["provider"] = "kenney",
                        ["license"] = "CC0",
                        ["extracted_dir"] = assetsDir
                    }
                };
            }
            catch (Exception ex)
            {
                return new DownloadResult { Success = false, Error = ex.Message };
            }
        }

        public Task<List<AssetSearchResult>> SearchAsync(string query, AssetCategory? category = null)
        {
            // Kenney doesn't have a search API - return empty
            return Task.FromResult(new List<AssetSearchResult>());
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
