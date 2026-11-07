"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import time
import requests
from requests.exceptions import (SSLError, RequestException, HTTPError)
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.models.helpers import is_bundle_version_compatible
from cereal import custom


class ModelParser:
  """Handles parsing of model data into cereal objects"""

  @staticmethod
  def _parse_download_uri(download_uri_data) -> custom.ModelManagerSP.DownloadUri:
    download_uri = custom.ModelManagerSP.DownloadUri()
    download_uri.uri = download_uri_data.get("url")
    download_uri.sha256 = download_uri_data.get("sha256")
    return download_uri

  @staticmethod
  def _parse_artifact(artifact_data) -> custom.ModelManagerSP.Artifact:
    artifact = custom.ModelManagerSP.Artifact()
    artifact.fileName = artifact_data.get("file_name")
    artifact.downloadUri = ModelParser._parse_download_uri(artifact_data.get("download_uri", {}))
    return artifact

  @staticmethod
  def _parse_model(model_data) -> custom.ModelManagerSP.Model:
    model = custom.ModelManagerSP.Model()

    model.type = model_data.get("type")
    model.artifact = ModelParser._parse_artifact(model_data.get("artifact", {}))
    return model

  @staticmethod
  def _parse_overrides(overrides_data: dict[str, str]) -> list[custom.ModelManagerSP.Override]:
    overrides = []
    for key, value in overrides_data.items():
      override = custom.ModelManagerSP.Override()
      override.key = key
      override.value = value
      overrides.append(override)
    return overrides

  @staticmethod
  def _parse_bundle(bundle) -> custom.ModelManagerSP.ModelBundle:
    model_bundle = custom.ModelManagerSP.ModelBundle()
    model_bundle.index = int(bundle["index"])
    model_bundle.internalName = bundle["short_name"]
    model_bundle.displayName = bundle["display_name"]
    model_bundle.models = [ModelParser._parse_model(model) for model in bundle.get("models",[])]
    model_bundle.status = 0
    model_bundle.generation = int(bundle["generation"])
    model_bundle.environment = bundle["environment"]
    model_bundle.runner = bundle.get("runner", custom.ModelManagerSP.Runner.snpe)
    model_bundle.is20hz = bundle.get("is_20hz", False)
    model_bundle.minimumSelectorVersion = int(bundle["minimum_selector_version"])
    model_bundle.overrides = ModelParser._parse_overrides(bundle.get("overrides", {}))
    model_bundle.ref = bundle.get("ref")

    return model_bundle

  @staticmethod
  def parse_models(json_data: dict) -> list[custom.ModelManagerSP.ModelBundle]:
    found_bundles = [ModelParser._parse_bundle(bundle) for bundle in json_data.get("bundles", [])]
    return [bundle for bundle in found_bundles if is_bundle_version_compatible(bundle.to_dict())]


class ModelCache:
  """Handles caching of model data to avoid frequent remote fetches"""

  def __init__(self, params: Params, cache_timeout: int = int(3600 * 1e9), suffix: str = ""):
    self.params = params
    self.cache_timeout = cache_timeout
    self._LAST_SYNC_KEY = f"ModelManager_LastSyncTime{suffix}"
    self._CACHE_KEY = f"ModelManager_ModelsCache{suffix}"

  def _is_expired(self) -> bool:
    """Checks if the cache has expired"""
    current_time = int(time.monotonic() * 1e9)
    last_sync = self.params.get(self._LAST_SYNC_KEY) or 0
    return bool(last_sync == 0) or (current_time - last_sync) >= self.cache_timeout

  def get(self) -> tuple[dict, bool]:
    """
    Retrieves cached model data and expiration status atomically.
    Returns: Tuple of (cached_data, is_expired)
    If no cached data exists or on error, returns an empty dict
    """
    try:
      cached_data = self.params.get(self._CACHE_KEY)
      if not cached_data:
        cloudlog.warning("No cached model data available")
        return {}, True
      return cached_data, self._is_expired()
    except Exception as e:
      cloudlog.exception(f"Error retrieving cached model data: {str(e)}")
      return {}, True

  def set(self, data: dict) -> None:
    """Updates the cache with new model data"""
    self.params.put(self._CACHE_KEY, data, block=True)
    self.params.put(self._LAST_SYNC_KEY, int(time.monotonic() * 1e9), block=True)


class ModelFetcher:
  """Handles fetching and caching of model data from remote source"""
  MODEL_URL = "https://raw.githubusercontent.com/sunnypilot/sunnypilot-models/refs/heads/gh-pages/docs/driving_models_v25.json"
  MODEL_URL_CHESTNUT = "https://raw.githubusercontent.com/sunnypilot/sunnypilot-models/refs/heads/gh-pages/docs/driving_models_chestnut_v28.json"

  MODEL_SOURCES = {
    "qcom": (MODEL_URL, ""),
    "chestnut": (MODEL_URL_CHESTNUT, "_Chestnut"),
  }

  def __init__(self, params: Params):
    self.params = params
    self.model_parser = ModelParser()
    self.model_caches = {
      source: ModelCache(params, suffix=suffix)
      for source, (_, suffix) in self.MODEL_SOURCES.items()
    }
    self._refetched: set[str] = set()
    # 本机补丁（2026-10-29，随 2026-11-03 模型管理同步重新移植）：缓存解析记忆化。manager 1Hz
    # 循环每秒都会走 get_bundles_for_source()，而 124 KB / 68 个 bundle 的 parse 要 ~97 ms，
    # 白烧约 10% CPU。这里按各 source 的 LastSyncTime 时间戳做指纹缓存解析结果（不能用
    # repr(cached_data)，那等于每秒把 124KB 重新序列化一遍）。另加拉取失败退避，离线时不要
    # 每 1Hz 都去撞 10s 超时。
    self._parsed_cache_key: dict[str, int | None] = {s: None for s in self.MODEL_SOURCES}
    self._parsed_cache: dict[str, list] = {s: [] for s in self.MODEL_SOURCES}
    self._next_fetch_at: dict[str, float] = {s: 0.0 for s in self.MODEL_SOURCES}
    self._fetch_backoff: dict[str, float] = {s: 10.0 for s in self.MODEL_SOURCES}
    self.params.put("ModelManager_ActiveJson", {
      "qcom": self.MODEL_URL,
      "chestnut": self.MODEL_URL_CHESTNUT,
    }, block=True)

  def _parse_cached(self, source: str, cached_data: dict) -> list[custom.ModelManagerSP.ModelBundle]:
    """带记忆化的 parse。key 用该 source 的缓存同步时间戳，缓存内容一变自动失效。"""
    key = self.params.get(self.model_caches[source]._LAST_SYNC_KEY) or 0
    if self._parsed_cache_key[source] != key:
      self._parsed_cache[source] = self.model_parser.parse_models(cached_data)
      self._parsed_cache_key[source] = key
    return self._parsed_cache[source]

  def _invalidate_parse_cache(self, source: str) -> None:
    self._parsed_cache_key[source] = None
    self._parsed_cache[source] = []

  def _may_fetch(self, source: str) -> bool:
    return time.monotonic() >= self._next_fetch_at[source]

  def _on_fetch_result(self, source: str, ok: bool) -> None:
    if ok:
      self._fetch_backoff[source] = 10.0
      self._next_fetch_at[source] = 0.0
    else:
      self._next_fetch_at[source] = time.monotonic() + self._fetch_backoff[source]
      self._fetch_backoff[source] = min(self._fetch_backoff[source] * 2.0, 600.0)

  @staticmethod
  def active_source(chestnut_present: bool) -> str:
    return "chestnut" if chestnut_present else "qcom"

  def _fetch_and_cache_models(self, source: str) -> list[custom.ModelManagerSP.ModelBundle] | None:
    """Fetches fresh model data from remote and updates cache.
    Returns None on transport errors. Raises on 404 and other fatal HTTP errors.
    """
    model_url, _ = self.MODEL_SOURCES[source]
    try:
      response = requests.get(model_url, timeout=10)

      # Explicitly handle 404 differently
      if response.status_code == 404:
        cloudlog.error(f"Models URL returned 404 Not Found: {model_url}")
        raise HTTPError(f"404 Not Found: {model_url}", response=response)

      # Raise for any other 4xx/5xx
      response.raise_for_status()

      json_data = response.json()
      parsed = self.model_parser.parse_models(json_data)
      if parsed:
        self.model_caches[source].set(json_data)
        cloudlog.debug(f"Successfully updated models cache for {source}")
      return parsed

    except ConnectionError as e:
      cloudlog.warning(f"DNS/connection error while fetching models: {e}")
    except SSLError as e:
      cloudlog.warning(f"SSL error while fetching models: {e}")
    except RequestException as e:
      cloudlog.warning(f"Request transport error while fetching models: {e}")
    except Exception as e:
      cloudlog.exception(f"Unexpected error fetching models: {e}")

    return None

  @staticmethod
  def _cache_matches_source(source: str, cached_data: dict) -> bool:
    bundles = cached_data.get("bundles", [])
    if source == "chestnut":
      return any(bundle.get("is_big") is True for bundle in bundles)
    return not any(bundle.get("is_big") is True for bundle in bundles)

  def get_bundles_for_source(self, source: str) -> list[custom.ModelManagerSP.ModelBundle]:
    if source not in self.MODEL_SOURCES:
      cloudlog.warning(f"Unknown model source: {source}")
      return []

    cached_data, is_expired = self.model_caches[source].get()

    if cached_data and not is_expired:
      # a source is refetched over a mismatch at most once per process: if the fresh
      # manifest still mismatches, the URL is authoritative and the cache is trusted
      if self._cache_matches_source(source, cached_data) or source in self._refetched:
        try:
          parsed = self._parse_cached(source, cached_data)
        except Exception:
          cloudlog.warning(f"Failed to parse cached models for {source}; refetching", exc_info=True)
        else:
          if parsed:
            cloudlog.debug(f"Using valid cached models data for source {source}")
            return parsed
          # a source-matching cache that yields no valid bundles is stale (e.g. an old
          # manifest version) - do not trust it, refetch so the source is repopulated
          cloudlog.warning(f"Cached models for {source} have no valid bundles; refetching")
      else:
        self._refetched.add(source)
        cloudlog.warning(f"Cached models for {source} not valid; refetching once")

    # 本机补丁：上一次拉取失败、还在退避窗口里，就用（已过期的）缓存，别去撞网络
    if cached_data and not self._may_fetch(source):
      try:
        return self._parse_cached(source, cached_data)
      except Exception:
        cloudlog.warning(f"Failed to parse expired cached models for {source}", exc_info=True)
        return []

    fetched_bundles = self._fetch_and_cache_models(source)
    self._on_fetch_result(source, fetched_bundles is not None)
    if fetched_bundles is not None:
      return fetched_bundles

    if not cached_data:
      cloudlog.warning("Failed to fetch fresh data and no cache available")

    cloudlog.warning("Failed to fetch fresh data. Using expired cache as fallback")
    try:
      return self._parse_cached(source, cached_data)
    except Exception:
      return []


def get_cached_bundles(params: Params, source: str) -> list[custom.ModelManagerSP.ModelBundle]:

  if source not in ModelFetcher.MODEL_SOURCES:
    cloudlog.warning(f"Unknown model source: {source}")
    return []
  _, suffix = ModelFetcher.MODEL_SOURCES[source]
  cached_data = params.get(f"ModelManager_ModelsCache{suffix}")
  if not cached_data:
    return []
  try:
    return ModelParser.parse_models(cached_data)
  except Exception as e:
    cloudlog.warning(f"Failed to parse cached models for source {source}: {e}")
    return []


if __name__ == "__main__":
  from openpilot.selfdrive.modeld.helpers import chestnut_present
  params = Params()
  model_fetcher = ModelFetcher(params)
  bundles = model_fetcher.get_bundles_for_source(ModelFetcher.active_source(chestnut_present()))
  for bundle in bundles:
    for model in bundle.models:
      model_overrides = {override.key: override.value for override in bundle.overrides}
      print(f"Bundle: {bundle.internalName}, Type: {model.type}, Status: {bundle.status}, Overrides: {model_overrides}")
      print(f"Artifact: {model.artifact.fileName}, Download URI: {model.artifact.downloadUri.uri}")
