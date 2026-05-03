using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace FAW.Providers
{
    public enum AssetCategory
    {
        Texture,
        Model,
        Audio,
        Animation,
        Material,
        HDR,
        Font,
        VFX,
        Sprite,
        Unknown
    }

    public class ProviderConfig
    {
        public string ApiKey { get; set; }
        public string ApiSecret { get; set; }
        public string AuthToken { get; set; }
        public string BaseUrl { get; set; }
        public int TimeoutSeconds { get; set; } = 120;
        public bool Enabled { get; set; } = true;
    }

    public class DownloadResult
    {
        public bool Success { get; set; }
        public string LocalPath { get; set; }
        public string AssetId { get; set; }
        public AssetCategory Category { get; set; }
        public string Format { get; set; }
        public long FileSizeBytes { get; set; }
        public string Sha256 { get; set; }
        public string Error { get; set; }
        public Dictionary<string, string> Metadata { get; set; } = new();

        public JObject ToJson()
        {
            return new JObject
            {
                ["success"] = Success,
                ["local_path"] = LocalPath,
                ["asset_id"] = AssetId,
                ["category"] = Category.ToString().ToLowerInvariant(),
                ["format"] = Format,
                ["file_size_bytes"] = FileSizeBytes,
                ["sha256"] = Sha256,
                ["error"] = Error
            };
        }
    }

    public class AssetSearchResult
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public AssetCategory Category { get; set; }
        public string ThumbnailUrl { get; set; }
        public string Provider { get; set; }
        public long FileSizeBytes { get; set; }
        public string[] Formats { get; set; }
        public Dictionary<string, string> Tags { get; set; } = new();
    }

    public interface IAssetProvider
    {
        string Id { get; }
        string Name { get; }
        string Description { get; }
        bool RequiresAuth { get; }
        bool IsFree { get; }
        AssetCategory[] SupportedCategories { get; }

        Task<bool> AuthenticateAsync(ProviderConfig config);
        Task<DownloadResult> DownloadAsync(string assetId, ProviderConfig config);
        Task<List<AssetSearchResult>> SearchAsync(string query, AssetCategory? category = null);
        Task<bool> ValidateAsync(string localPath);
    }
}
