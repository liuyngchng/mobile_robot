#!/usr/bin/env python3
"""
知识库向量化脚本

将 markdown 文件或知识库 JSON 中的文本块，调用在线 Embedding API 进行向量化。

用法:
  # 从 markdown 文件分块并向量化，生成知识库 JSON
  python3 embed_knowledge.py readme.md -o knowledge.json

  # 填充已有 JSON 中的空 embedding
  python3 embed_knowledge.py knowledge.json -o knowledge_embedded.json

  # 指定公司名称
  python3 embed_knowledge.py readme.md -o knowledge.json --company "昆昆燃气"

API 配置 (环境变量):
  EMBEDDING_API_KEY    - API Key
  EMBEDDING_BASE_URL   - API Base URL (默认: https://dashscope.aliyuncs.com/compatible-mode/v1)
  EMBEDDING_MODEL      - 模型名 (默认: text-embedding-v3)

支持的 API (OpenAI 兼容接口):
  - 阿里百炼 DashScope:   base_url=https://dashscope.aliyuncs.com/compatible-mode/v1, model=text-embedding-v3
  - OpenAI:               base_url=https://api.openai.com/v1, model=text-embedding-3-small
  - DeepSeek:             base_url=https://api.deepseek.com/v1, model=deepseek-embedding
  - 硅基流动 SiliconFlow:  base_url=https://api.siliconflow.cn/v1, model=BAAI/bge-large-zh-v1.5
  - 其他 OpenAI 兼容接口:  按实际配置
"""

import argparse
import json
import os
import re
import sys
import time
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# 默认配置（优先使用阿里百炼，国内访问最稳定）
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "text-embedding-v3"


def get_api_config() -> dict:
    """从环境变量读取 API 配置。"""
    api_key = os.environ.get("EMBEDDING_API_KEY")
    if not api_key:
        # 尝试读取通用的 OPENAI_API_KEY
        api_key = os.environ.get("OPENAI_API_KEY")
    # 阿里百炼的 key: DASHSCOPE_API_KEY
    if not api_key:
        api_key = os.environ.get("DASHSCOPE_API_KEY")

    return {
        "api_key": api_key,
        "base_url": os.environ.get("EMBEDDING_BASE_URL", DEFAULT_BASE_URL),
        "model": os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL),
    }


# ---------------------------------------------------------------------------
# Markdown 分块
# ---------------------------------------------------------------------------
def split_markdown(text: str, max_chars: int = 300) -> list[dict]:
    """
    将 markdown 文本按标题分块，超长段落再细分为句子级块。

    返回: [{"text": "...", "keywords": [...]}, ...]
    """
    # 按 ## / ### 标题切分（跳过一级标题 # ，它通常是文档标题）
    sections = re.split(r"\n(?=## )", text.strip())

    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 提取标题行
        title_match = re.match(r"^(#{1,3})\s+(.+)$", section, re.MULTILINE)
        title = title_match.group(2).strip() if title_match else ""

        # 提取正文（去掉标题行）
        body = section
        if title_match:
            body = section[title_match.end() :].strip()

        if not body:
            continue

        # 如果正文不超过 max_chars，直接作为一个 chunk
        if len(body) <= max_chars:
            chunks.append(
                {
                    "text": f"{title}\n{body}" if title else body,
                    "keywords": extract_keywords(title, body),
                }
            )
        else:
            # 按段落拆分
            paragraphs = re.split(r"\n\n+", body)
            current_text = title + "\n" if title else ""
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                # 如果加上这段不超过上限，追加
                if len(current_text) + len(para) + 2 <= max_chars:
                    current_text += ("\n" + para if current_text else para)
                else:
                    # 保存当前块
                    if current_text.strip():
                        chunks.append(
                            {
                                "text": current_text.strip(),
                                "keywords": extract_keywords(title or current_text, ""),
                            }
                        )
                    # 开始新块
                    current_text = (title + "\n" + para) if title else para

            # 收尾
            if current_text.strip():
                chunks.append(
                    {
                        "text": current_text.strip(),
                        "keywords": extract_keywords(title, ""),
                    }
                )

    return chunks


def extract_keywords(title: str, body: str) -> list[str]:
    """
    从标题和正文提取关键词。简单实现：提取引号中的词 + 标题中的名词短语。
    更复杂的关键词提取可以接入 NLP 工具。
    """
    keywords = []
    text = f"{title} {body}"

    # 提取中文书名号 / 引号内容
    quoted = re.findall(r"[「『《](.+?)[」』》]", text)
    keywords.extend(quoted)

    # 提取英文双引号内容
    quoted_en = re.findall(r'"(.+?)"', text)
    keywords.extend(quoted_en)

    # 如果标题看起来是关键词型（如"营业厅"），加入标题拆分的短语
    if title:
        # 按标点拆分标题
        title_parts = re.split(r"[，,、\s]+", title)
        for part in title_parts:
            part = part.strip()
            if len(part) >= 2 and len(part) <= 10:
                keywords.append(part)

    # 去重，保留顺序
    seen = set()
    unique = []
    for k in keywords:
        k = k.strip()
        if k and k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


# ---------------------------------------------------------------------------
# Embedding API 调用
# ---------------------------------------------------------------------------
def call_embedding_api(
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    max_retries: int = 3,
) -> list[list[float]]:
    """
    调用 OpenAI 兼容的 Embedding API。

    阿里百炼、OpenAI、DeepSeek、硅基流动等均支持相同接口。
    """
    url = base_url.rstrip("/") + "/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": texts,
        "encoding_format": "float",
    }

    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                # 按 index 排序后返回 embedding 列表
                items = sorted(data["data"], key=lambda x: x["index"])
                embeddings = [item["embedding"] for item in items]
                return embeddings
            else:
                # 4xx 错误不重试
                if 400 <= resp.status_code < 500:
                    print(f"[错误] API 返回 {resp.status_code}: {resp.text}", file=sys.stderr)
                    return []
                last_error = f"HTTP {resp.status_code}: {resp.text}"
        except requests.exceptions.Timeout:
            last_error = "请求超时"
        except requests.exceptions.ConnectionError as e:
            last_error = f"连接失败: {e}"
        except Exception as e:
            last_error = str(e)

        if attempt < max_retries - 1:
            wait = 2 ** attempt
            print(f"[重试] {last_error}，{wait}s 后重试 ({attempt + 2}/{max_retries})", file=sys.stderr)
            time.sleep(wait)

    print(f"[错误] API 调用失败（已重试 {max_retries} 次）: {last_error}", file=sys.stderr)
    return []


def embed_chunks(
    chunks: list[dict],
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int = 20,
    dry_run: bool = False,
) -> list[dict]:
    """
    批量对 chunk 进行向量化。

    参数:
        chunks: 包含 "text" 键的 chunk 列表
        batch_size: 每次 API 调用发送的文本数量（阿里百炼最多支持 25 条/请求）
        dry_run: 仅打印将要向量化的内容，不实际调用 API
    """
    if dry_run:
        print(f"[预览] 共 {len(chunks)} 个文本块，将分 { (len(chunks) + batch_size - 1) // batch_size } 批提交")
        for i, c in enumerate(chunks):
            text_preview = c["text"][:80].replace("\n", " ")
            print(f"  [{i}] {text_preview}...")
        return chunks

    total_batches = (len(chunks) + batch_size - 1) // batch_size
    processed = 0

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(chunks))
        batch = chunks[start:end]
        texts = [c["text"] for c in batch]

        print(
            f"[向量化] 批次 {batch_idx + 1}/{total_batches}，{len(texts)} 条文本...",
            file=sys.stderr,
        )

        embeddings = call_embedding_api(texts, api_key, base_url, model)

        if embeddings and len(embeddings) == len(texts):
            for i, emb in enumerate(embeddings):
                chunks[start + i]["embedding"] = emb
            processed += len(texts)
            print(f"  ✓ 完成 ({processed}/{len(chunks)})", file=sys.stderr)
        else:
            print(f"  ✗ 批次失败，embedding 保持为空", file=sys.stderr)

        # 批次间短暂停顿，避免限流
        if batch_idx < total_batches - 1:
            time.sleep(0.3)

    return chunks


# ---------------------------------------------------------------------------
# JSON 知识库处理
# ---------------------------------------------------------------------------
def load_knowledge_json(filepath: str) -> dict:
    """加载知识库 JSON 文件。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def save_knowledge_json(data: dict, filepath: str):
    """保存知识库 JSON 文件。"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[完成] 已保存到: {filepath}")


def is_json_file(filepath: str) -> bool:
    """判断是否为 JSON 文件。"""
    return filepath.lower().endswith(".json")


def markdown_to_knowledge_json(text: str, company_name: str = "") -> dict:
    """将 markdown 文本转为知识库 JSON 结构。"""
    chunks = split_markdown(text)
    knowledge_chunks = []
    for i, c in enumerate(chunks):
        knowledge_chunks.append(
            {
                "id": str(i + 1),
                "text": c["text"],
                "keywords": c["keywords"],
                "embedding": [],
            }
        )

    result = {"version": 1, "chunks": knowledge_chunks}
    if company_name:
        result["companyName"] = company_name
    return result


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="知识库文本向量化 — 调用在线 Embedding API 为 markdown/JSON 中的文本块生成向量",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 从 markdown 生成知识库 JSON（含向量）
  python3 embed_knowledge.py readme.md -o knowledge.json

  # 填充已有 JSON 中的空 embedding
  python3 embed_knowledge.py knowledge.json -o knowledge_full.json

  # 预览分块结果，不调用 API
  python3 embed_knowledge.py readme.md --dry-run

  # 使用阿里百炼
  export EMBEDDING_API_KEY="sk-xxx"
  export EMBEDDING_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
  export EMBEDDING_MODEL="text-embedding-v3"
  python3 embed_knowledge.py readme.md -o knowledge.json

  # 使用硅基流动
  export EMBEDDING_API_KEY="sk-xxx"
  export EMBEDDING_BASE_URL="https://api.siliconflow.cn/v1"
  export EMBEDDING_MODEL="BAAI/bge-large-zh-v1.5"
  python3 embed_knowledge.py readme.md -o knowledge.json
        """,
    )
    parser.add_argument("input", help="输入文件：markdown (.md) 或知识库 JSON (.json)")
    parser.add_argument("-o", "--output", default="knowledge_embedded.json", help="输出 JSON 文件路径 (默认: knowledge_embedded.json)")
    parser.add_argument("--company", default="", help="公司名称 (从 markdown 生成时使用)")
    parser.add_argument("--max-chars", type=int, default=300, help="每块最大字符数 (默认: 300)")
    parser.add_argument("--batch-size", type=int, default=20, help="每批 API 调用的文本数 (默认: 20)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览分块，不调用 API")
    parser.add_argument("--api-key", default="", help="API Key (优先于环境变量)")
    parser.add_argument("--base-url", default="", help="API Base URL (优先于环境变量)")
    parser.add_argument("--model", default="", help="Embedding 模型名 (优先于环境变量)")

    args = parser.parse_args()

    # --- 读取输入 ---
    if not os.path.exists(args.input):
        print(f"[错误] 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        raw_text = f.read()

    # --- 解析为知识库结构 ---
    if is_json_file(args.input):
        print(f"[输入] JSON 知识库: {args.input}")
        kb = json.loads(raw_text)
        chunks = kb.get("chunks", [])
        if not chunks:
            print("[错误] JSON 中没有 chunks 字段", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"[输入] Markdown 文件: {args.input}")
        kb = markdown_to_knowledge_json(raw_text, company_name=args.company)
        chunks = kb["chunks"]

    if not chunks:
        print("[错误] 没有提取到任何文本块", file=sys.stderr)
        sys.exit(1)

    print(f"[分块] 共 {len(chunks)} 个文本块 (max_chars={args.max_chars})")

    # --- 过滤已向量化的 chunk ---
    pending_chunks = [c for c in chunks if not c.get("embedding") or len(c["embedding"]) == 0]
    already_done = len(chunks) - len(pending_chunks)
    if already_done > 0:
        print(f"[状态] {already_done} 个已有向量，{len(pending_chunks)} 个待处理")

    # --- 预览 ---
    if args.dry_run:
        for i, c in enumerate(chunks):
            has_emb = bool(c.get("embedding") and len(c["embedding"]) > 0)
            status = "✓" if has_emb else "○"
            text_preview = c["text"][:100].replace("\n", " ")
            print(f"  [{i}] {status} {text_preview}...")
        print(f"\n共 {len(chunks)} 块，{len(pending_chunks)} 块待处理。去掉 --dry-run 执行实际向量化。")
        return

    if not pending_chunks:
        print("[完成] 所有 chunk 已有向量，无需处理。")
        save_knowledge_json(kb, args.output)
        return

    # --- API 配置 ---
    config = get_api_config()
    api_key = args.api_key or config["api_key"]
    base_url = args.base_url or config["base_url"]
    model = args.model or config["model"]

    if not api_key:
        print(
            "[错误] 未设置 API Key。请设置环境变量 EMBEDDING_API_KEY 或通过 --api-key 参数传入。\n"
            "  阿里百炼: export EMBEDDING_API_KEY='sk-xxx'\n"
            "  OpenAI:   export EMBEDDING_API_KEY='sk-xxx' EMBEDDING_BASE_URL='https://api.openai.com/v1' EMBEDDING_MODEL='text-embedding-3-small'",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[API] {model} @ {base_url}")

    # --- 向量化 ---
    pending_chunks = embed_chunks(
        pending_chunks,
        api_key=api_key,
        base_url=base_url,
        model=model,
        batch_size=args.batch_size,
    )

    # --- 检查结果 ---
    vec_count = sum(1 for c in chunks if c.get("embedding") and len(c["embedding"]) > 0)
    print(f"[结果] {vec_count}/{len(chunks)} 个 chunk 已向量化")

    if vec_count > 0:
        dim = len(next(c["embedding"] for c in chunks if c.get("embedding") and len(c["embedding"]) > 0))
        print(f"[维度] 向量维度: {dim}")
        # 验证所有向量维度一致
        all_same = all(
            len(c["embedding"]) == dim
            for c in chunks
            if c.get("embedding") and len(c["embedding"]) > 0
        )
        if not all_same:
            print("[警告] 检测到部分 chunk 向量维度不一致!", file=sys.stderr)

    save_knowledge_json(kb, args.output)


if __name__ == "__main__":
    main()
