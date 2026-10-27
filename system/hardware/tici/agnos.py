#!/usr/bin/env python3
import hashlib
import json
import lzma
import os
import struct
import subprocess
import time
from collections.abc import Generator

import requests

import openpilot.system.updated.casync.casync as casync

SPARSE_CHUNK_FMT = struct.Struct('H2xI4x')
CAIBX_URL = "https://commadist.azureedge.net/agnosupdate/"

AGNOS_MANIFEST_FILE = "system/hardware/tici/agnos.json"

# BluePilot: fork 自改的引导链分区，绝不允许刷进设备。
#
# bp7 分支自带的 agnos.json 里 abl / boot 的 hash 是这个 fork 自己改过的
# （abl=b6fba807…、boot=19ff57b6…），并不是官方镜像。设备 bootloader 会校验
# 这两个分区，hash 对不上就拒绝加载 → "Unsupported firmware detected"，
# 设备直接变砖。历史上已经因此变砖两次。
#
# 这里做硬拦截：只要待刷清单里的引导链分区命中这些 hash，直接抛异常中止，
# 宁可 AGNOS 不升级，也不碰引导链。所有刷引导链的入口都经过
# flash_agnos_update()，所以在这里拦一次就全线封死。
FORK_MODIFIED_BOOT_CHAIN = {
  # name -> (hash_raw 前缀, 说明)
  "abl": ("b6fba807b9bcd66a31f2afb0eba5163ec239693ad32e2e4200f6c356adfe098c",
          "fork 自改的 ABL（bootloader）"),
  "boot": ("19ff57b68e219e4503fcaca716967098d5d0a1de8af833f04dbf13b99aeb4d39",
           "fork 自改的 boot 内核"),
}


def assert_official_boot_chain(update: list[dict]) -> None:
  """拒绝刷入 fork 自改的引导链分区。命中即抛异常，中止整个 AGNOS 更新。"""
  for partition in update:
    name = partition.get("name")
    entry = FORK_MODIFIED_BOOT_CHAIN.get(name)
    if entry is None:
      continue
    forbidden_hash, desc = entry
    actual = str(partition.get("hash_raw", "")).lower()
    if actual == forbidden_hash.lower():
      raise RuntimeError(
        f"拒绝刷引导链：清单里的 {name} 是 {desc}（hash={actual[:16]}…）。"
        f"设备 bootloader 会拒绝加载它，刷进去必然变砖（Unsupported firmware detected）。"
        f"已中止本次 AGNOS 更新，设备分区未被改动。"
      )


# 引导链分区名 —— 这些分区属于 bootloader 链，与 openpilot 用户空间无关，
# 但刷错版本会让设备彻底起不来（连 SSH 都没有，只能 QDL 全刷）。
BOOT_CHAIN_PARTITIONS = ("xbl", "xbl_config", "abl", "aop", "devcfg", "boot")

# 本仓库随附的 agnos.json 对应的 AGNOS 版本。
# 清单里的 url 只有 hash（commadist 靠 hash 寻址，不带版本号），所以版本只能
# 在源码里标注。这个值与仓库的 18.5 底包一致 —— 历史确认过 bp7 的
# agnos.json 是 AGNOS 18.5 的整套镜像。
MANIFEST_AGNOS_VERSION = "18.5"


def assert_boot_chain_matches_device(update: list[dict]) -> None:
  """拒绝把「与当前设备 bootloader 不匹配」的引导链刷进去。

  背景：bp7 自带的 agnos.json 指向 AGNOS 18.5 的整套镜像，包含 18.5 的
  xbl/abl/boot。而设备的 bootloader（装在 xbl/abl 分区里）是出厂时那一版。
  AGNOS 的 xbl 与设备硬件强绑定 —— 把别的硬件世代的 xbl 刷进去，bootloader
  直接拒绝加载，设备变砖。

  低版本设备（12.x / 13.x）刷 18.5 的引导链必然踩中：历史上两次变砖
  都是这个原因。而 FORK_MODIFIED_BOOT_CHAIN 只能识别「已知的自改哈希」，
  识别不了「官方但版本不匹配」的情况 —— 所以这里补一道版本闸。

  判据：实机 /VERSION 必须等于本清单对应的 AGNOS 版本，否则拒绝整份清单。
  """
  device_version = ""
  try:
    with open("/VERSION") as f:
      device_version = f.read().strip()
  except OSError:
    device_version = ""

  if not device_version:
    # 读不到实机版本，无从判断 —— 不在这里拦，交给上面的哈希闸。
    return

  if device_version == MANIFEST_AGNOS_VERSION:
    return

  raise RuntimeError(
    f"拒绝刷引导链：本清单对应 AGNOS {MANIFEST_AGNOS_VERSION}，而设备实机是 "
    f"{device_version}。boot 与 system 是版本绑定的，引导链与硬件世代也强绑定 —— "
    f"刷进去 bootloader 会拒绝加载，设备直接变砖（Unsupported firmware detected，"
    f"SSH 与网络全断，只能 QDL 全刷救砖）。已中止本次 AGNOS 更新，设备分区未被改动。"
  )



class StreamingDecompressor:
  def __init__(self, url: str) -> None:
    self.buf = b""

    self.req = requests.get(url, stream=True, headers={'Accept-Encoding': None}, timeout=60)
    self.it = self.req.iter_content(chunk_size=1024 * 1024)
    self.decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO)
    self.eof = False
    self.sha256 = hashlib.sha256()

  def read(self, length: int) -> bytes:
    while len(self.buf) < length and not self.eof:
      if self.decompressor.needs_input:
        self.req.raise_for_status()

        try:
          compressed = next(self.it)
        except StopIteration:
          self.eof = True
          break
      else:
        compressed = b''

      self.buf += self.decompressor.decompress(compressed, max_length=length)

      if self.decompressor.eof:
        self.eof = True
        break

    result = self.buf[:length]
    self.buf = self.buf[length:]

    self.sha256.update(result)
    return result


def unsparsify(f: StreamingDecompressor) -> Generator[bytes, None, None]:
  # https://source.android.com/devices/bootloader/images#sparse-format
  magic = struct.unpack("I", f.read(4))[0]
  assert(magic == 0xed26ff3a)

  # Version
  major = struct.unpack("H", f.read(2))[0]
  minor = struct.unpack("H", f.read(2))[0]
  assert(major == 1 and minor == 0)

  f.read(2)  # file header size
  f.read(2)  # chunk header size

  block_sz = struct.unpack("I", f.read(4))[0]
  f.read(4)  # total blocks
  num_chunks = struct.unpack("I", f.read(4))[0]
  f.read(4)  # crc checksum

  for _ in range(num_chunks):
    chunk_type, out_blocks = SPARSE_CHUNK_FMT.unpack(f.read(12))

    if chunk_type == 0xcac1:  # Raw
      # TODO: yield in smaller chunks. Yielding only block_sz is too slow. Largest observed data chunk is 252 MB.
      yield f.read(out_blocks * block_sz)
    elif chunk_type == 0xcac2:  # Fill
      filler = f.read(4) * (block_sz // 4)
      for _ in range(out_blocks):
        yield filler
    elif chunk_type == 0xcac3:  # Don't care
      yield b""
    else:
      raise Exception("Unhandled sparse chunk type")


# noop wrapper with same API as unsparsify() for non sparse images
def noop(f: StreamingDecompressor) -> Generator[bytes, None, None]:
  while len(chunk := f.read(1024 * 1024)) > 0:
    yield chunk


def get_target_slot_number() -> int:
  current_slot = subprocess.check_output(["abctl", "--boot_slot"], encoding='utf-8').strip()
  return 1 if current_slot == "_a" else 0


def slot_number_to_suffix(slot_number: int) -> str:
  assert slot_number in (0, 1)
  return '_a' if slot_number == 0 else '_b'


def get_partition_path(target_slot_number: int, partition: dict) -> str:
  path = f"/dev/disk/by-partlabel/{partition['name']}"

  if partition.get('has_ab', True):
    path += slot_number_to_suffix(target_slot_number)

  return path


def get_raw_hash(path: str, partition_size: int) -> str:
  raw_hash = hashlib.sha256()
  pos, chunk_size = 0, 1024 * 1024

  with open(path, 'rb+') as out:
    while pos < partition_size:
      n = min(chunk_size, partition_size - pos)
      raw_hash.update(out.read(n))
      pos += n

  return raw_hash.hexdigest().lower()


def verify_partition(target_slot_number: int, partition: dict[str, str | int], force_full_check: bool = False) -> bool:
  full_check = partition['full_check'] or force_full_check
  path = get_partition_path(target_slot_number, partition)

  if not isinstance(partition['size'], int):
    return False

  partition_size: int = partition['size']

  if not isinstance(partition['hash_raw'], str):
    return False

  partition_hash: str = partition['hash_raw']

  if full_check:
    return get_raw_hash(path, partition_size) == partition_hash.lower()
  else:
    with open(path, 'rb+') as out:
      out.seek(partition_size)
      return out.read(64) == partition_hash.lower().encode()


def clear_partition_hash(target_slot_number: int, partition: dict) -> None:
  path = get_partition_path(target_slot_number, partition)
  with open(path, 'wb+') as out:
    partition_size = partition['size']

    out.seek(partition_size)
    out.write(b"\x00" * 64)
    os.sync()


def extract_compressed_image(target_slot_number: int, partition: dict, cloudlog):
  path = get_partition_path(target_slot_number, partition)
  downloader = StreamingDecompressor(partition['url'])

  with open(path, 'wb+') as out:
    # Flash partition
    last_p = 0
    raw_hash = hashlib.sha256()
    f = unsparsify if partition['sparse'] else noop
    for chunk in f(downloader):
      raw_hash.update(chunk)
      out.write(chunk)
      p = int(out.tell() / partition['size'] * 100)
      if p != last_p:
        last_p = p
        print(f"Installing {partition['name']}: {p}", flush=True)

    if raw_hash.hexdigest().lower() != partition['hash_raw'].lower():
      raise Exception(f"Raw hash mismatch '{raw_hash.hexdigest().lower()}'")

    if downloader.sha256.hexdigest().lower() != partition['hash'].lower():
      raise Exception("Uncompressed hash mismatch")

    if out.tell() != partition['size']:
      raise Exception("Uncompressed size mismatch")

    os.sync()


def extract_casync_image(target_slot_number: int, partition: dict, cloudlog):
  path = get_partition_path(target_slot_number, partition)
  seed_path = path[:-1] + ('b' if path[-1] == 'a' else 'a')

  target = casync.parse_caibx(partition['casync_caibx'])

  sources: list[tuple[str, casync.ChunkReader, casync.ChunkDict]] = []

  # First source is the current partition.
  try:
    raw_hash = get_raw_hash(seed_path, partition['size'])
    caibx_url = f"{CAIBX_URL}{partition['name']}-{raw_hash}.caibx"

    try:
      cloudlog.info(f"casync fetching {caibx_url}")
      sources += [('seed', casync.FileChunkReader(seed_path), casync.build_chunk_dict(casync.parse_caibx(caibx_url)))]
    except requests.RequestException:
      cloudlog.error(f"casync failed to load {caibx_url}")
  except Exception:
    cloudlog.exception("casync failed to hash seed partition")

  # Second source is the target partition, this allows for resuming
  sources += [('target', casync.FileChunkReader(path), casync.build_chunk_dict(target))]

  # Finally we add the remote source to download any missing chunks
  sources += [('remote', casync.RemoteChunkReader(partition['casync_store']), casync.build_chunk_dict(target))]

  last_p = 0

  def progress(cur):
    nonlocal last_p
    p = int(cur / partition['size'] * 100)
    if p != last_p:
      last_p = p
      print(f"Installing {partition['name']}: {p}", flush=True)

  stats = casync.extract(target, sources, path, progress)
  cloudlog.error(f'casync done {json.dumps(stats)}')

  os.sync()
  if not verify_partition(target_slot_number, partition, force_full_check=True):
    raise Exception(f"Raw hash mismatch '{partition['hash_raw'].lower()}'")


def flash_partition(target_slot_number: int, partition: dict, cloudlog, standalone=False):
  cloudlog.info(f"Downloading and writing {partition['name']}")

  if verify_partition(target_slot_number, partition):
    cloudlog.info(f"Already flashed {partition['name']}")
    return

  # Clear hash before flashing in case we get interrupted
  full_check = partition['full_check']
  if not full_check:
    clear_partition_hash(target_slot_number, partition)

  path = get_partition_path(target_slot_number, partition)

  if ('casync_caibx' in partition) and not standalone:
    extract_casync_image(target_slot_number, partition, cloudlog)
  else:
    extract_compressed_image(target_slot_number, partition, cloudlog)

  # Write hash after successful flash
  if not full_check:
    with open(path, 'wb+') as out:
      out.seek(partition['size'])
      out.write(partition['hash_raw'].lower().encode())


def swap(manifest_path: str, target_slot_number: int, cloudlog) -> None:
  update = json.load(open(manifest_path))
  for partition in update:
    if not partition.get('full_check', False):
      clear_partition_hash(target_slot_number, partition)

  while True:
    out = subprocess.check_output(f"abctl --set_active {target_slot_number}", shell=True, stderr=subprocess.STDOUT, encoding='utf8')
    if ("No such file or directory" not in out) and ("lun as boot lun" in out):
      cloudlog.info(f"Swap successful {out}")
      break
    else:
      cloudlog.error(f"Swap failed {out}")


def flash_agnos_update(manifest_path: str, target_slot_number: int, cloudlog, standalone=False) -> None:
  update = json.load(open(manifest_path))

  # BluePilot: 先拦掉 fork 自改的引导链，再做任何写操作。
  # 这一步必须在 abctl --set_unbootable 之前，否则拦晚了会把目标槽标成
  # unbootable，留下一个刷了一半的槽位。
  assert_official_boot_chain(update)

  # BluePilot: 再拦「官方但与实机版本不匹配」的引导链。
  # 低版本设备（12.x / 13.x）刷 18.5 的引导链必然变砖 —— 上一道只认
  # 已知的自改哈希，识别不了这种情况。
  assert_boot_chain_matches_device(update)

  cloudlog.info(f"Target slot {target_slot_number}")

  # set target slot as unbootable
  os.system(f"abctl --set_unbootable {target_slot_number}")

  for partition in update:
    success = False

    for retries in range(10):
      try:
        flash_partition(target_slot_number, partition, cloudlog, standalone)
        success = True
        break

      except requests.exceptions.RequestException:
        cloudlog.exception("Failed")
        cloudlog.info(f"Failed to download {partition['name']}, retrying ({retries})")
        time.sleep(10)

    if not success:
      cloudlog.info(f"Failed to flash {partition['name']}, aborting")
      raise Exception("Maximum retries exceeded")

  cloudlog.info(f"AGNOS ready on slot {target_slot_number}")


def verify_agnos_update(manifest_path: str, target_slot_number: int) -> bool:
  update = json.load(open(manifest_path))
  return all(verify_partition(target_slot_number, partition) for partition in update)


if __name__ == "__main__":
  import argparse
  import logging

  parser = argparse.ArgumentParser(description="Flash and verify AGNOS update",
                                   formatter_class=argparse.ArgumentDefaultsHelpFormatter)

  parser.add_argument("--verify", action="store_true", help="Verify and perform swap if update ready")
  parser.add_argument("--swap", action="store_true", help="Verify and perform swap, downloads if necessary")
  parser.add_argument("manifest", help="Manifest json")
  args = parser.parse_args()

  logging.basicConfig(level=logging.INFO)

  target_slot_number = get_target_slot_number()
  if args.verify:
    if verify_agnos_update(args.manifest, target_slot_number):
      swap(args.manifest, target_slot_number, logging)
      exit(0)
    exit(1)
  elif args.swap:
    while not verify_agnos_update(args.manifest, target_slot_number):
      logging.error("Verification failed. Flashing AGNOS")
      flash_agnos_update(args.manifest, target_slot_number, logging, standalone=True)

    logging.warning(f"Verification succeeded. Swapping to slot {target_slot_number}")
    swap(args.manifest, target_slot_number, logging)
  else:
    flash_agnos_update(args.manifest, target_slot_number, logging, standalone=True)
