using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using FlaxEngine;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace FAW.Providers
{
    public class ProviderRegistry
    {
        private static ProviderRegistry _instance;
        public static ProviderRegistry Instance => _instance ??= new ProviderRegistry();

        private readonly List<IAssetProvider> _providers = new();
        private readonly Dictionary<string, ProviderConfig> _configs = new(StringComparer.OrdinalIgnoreCase);
        public int Count => _providers.Count;

        private ProviderRegistry()
        {
            ScanAndRegister();
        }

        private void ScanAndRegister()
        {
            // Register built-in providers
            var types = typeof(ProviderRegistry).Assembly.GetTypes()
                .Where(t => typeof(IAssetProvider).IsAssignableFrom(t) && !t.IsInterface && !t.IsAbstract);

            foreach (var type in types)
            {
                try
                {
                    var provider = (IAssetProvider)Activator.CreateInstance(type);
                    _providers.Add(provider);
                    Debug.Log($"[AssetWorker] Registered provider: {provider.Id} ({provider.Name})");
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[AssetWorker] Failed to register provider {type.Name}: {ex.Message}");
                }
            }

            // Load configs
            LoadConfigs();
        }

        private void LoadConfigs()
        {
            var configPath = Path.Combine(Globals.ProjectFolder, "FAW", "Config", "providers.json");
            if (!File.Exists(configPath)) return;

            var json = File.ReadAllText(configPath);
            var providersConfig = JObject.Parse(json);
            foreach (var prop in providersConfig.Properties())
            {
                _configs[prop.Name] = new ProviderConfig
                {
                    ApiKey = prop.Value["api_key"]?.ToString(),
                    ApiSecret = prop.Value["api_secret"]?.ToString(),
                    AuthToken = prop.Value["auth_token"]?.ToString(),
                    BaseUrl = prop.Value["base_url"]?.ToString(),
                    Enabled = prop.Value["enabled"]?.Value<bool>() ?? true,
                    TimeoutSeconds = prop.Value["timeout_seconds"]?.Value<int>() ?? 120
                };
            }
        }

        public IAssetProvider GetProvider(string id)
        {
            return _providers.FirstOrDefault(p => string.Equals(p.Id, id, StringComparison.OrdinalIgnoreCase));
        }

        public IAssetProvider GetProviderForCategory(AssetCategory category)
        {
            return _providers.FirstOrDefault(p => p.SupportedCategories.Contains(category));
        }

        public List<IAssetProvider> GetAllProviders()
        {
            return _providers.ToList();
        }

        public List<IAssetProvider> GetEnabledProviders()
        {
            return _providers.Where(p =>
            {
                if (_configs.TryGetValue(p.Id, out var cfg))
                    return cfg.Enabled;
                return true; // No config = enabled by default
            }).ToList();
        }

        public ProviderConfig GetConfig(string providerId)
        {
            if (_configs.TryGetValue(providerId, out var cfg))
                return cfg;
            return new ProviderConfig();
        }

        public JObject ListProviders()
        {
            var providers = new JArray();
            foreach (var p in _providers)
            {
                var cfg = GetConfig(p.Id);
                providers.Add(new JObject
                {
                    ["id"] = p.Id,
                    ["name"] = p.Name,
                    ["description"] = p.Description,
                    ["requires_auth"] = p.RequiresAuth,
                    ["is_free"] = p.IsFree,
                    ["enabled"] = cfg.Enabled,
                    ["categories"] = new JArray(p.SupportedCategories.Select(c => c.ToString().ToLowerInvariant()))
                });
            }
            return new JObject { ["providers"] = providers, ["count"] = providers.Count };
        }
    }
}
