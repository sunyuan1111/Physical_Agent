import { SearchOutlined } from "@ant-design/icons";
import { Button, Card, Empty, Input, InputNumber, List, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";
import { searchMemory } from "../api";
import type { MemoryChunk } from "../types";

interface MemorySearchPanelProps {
  onError: (error: Error) => void;
}

export function MemorySearchPanel({ onError }: MemorySearchPanelProps) {
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState("");
  const [sourceType, setSourceType] = useState("");
  const [limit, setLimit] = useState(5);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<MemoryChunk[]>([]);

  async function runSearch() {
    const text = query.trim();
    if (!text) {
      return;
    }
    setLoading(true);
    try {
      const response = await searchMemory(text, limit, tags, sourceType);
      setResults(response.results);
    } catch (error) {
      onError(error instanceof Error ? error : new Error(String(error)));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card
      className="panel memory-search"
      data-testid="memory-search-panel"
      title={
        <Space>
          <SearchOutlined />
          <Typography.Text strong>Memory / Search</Typography.Text>
        </Space>
      }
    >
      <Space.Compact className="search-line">
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onPressEnter={runSearch}
          placeholder="query"
        />
        <Button icon={<SearchOutlined />} loading={loading} onClick={runSearch}>
          Search
        </Button>
      </Space.Compact>
      <div className="three-col compact-controls">
        <Input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="tags" />
        <Select
          value={sourceType}
          onChange={setSourceType}
          options={[
            { value: "", label: "all" },
            { value: "upload", label: "upload" },
            { value: "memory", label: "memory" }
          ]}
        />
        <InputNumber
          value={limit}
          min={1}
          max={20}
          onChange={(value) => setLimit(Number(value ?? 5))}
          className="full-width"
        />
      </div>
      {results.length ? (
        <List
          size="small"
          dataSource={results}
          renderItem={(item) => (
            <List.Item className="search-result">
              <List.Item.Meta
                title={
                  <Space size={6} wrap>
                    <Typography.Text code>
                      {item.source_type}:{item.chunk_index ?? 0}
                    </Typography.Text>
                    <Tag color={item.trust_level === "untrusted" ? "gold" : "green"}>
                      {item.trust_level ?? "unknown"}
                    </Tag>
                    <Tag>score {item.score ?? 0}</Tag>
                  </Space>
                }
                description={
                  <Typography.Paragraph ellipsis={{ rows: 4, expandable: true }}>
                    {item.content ?? ""}
                  </Typography.Paragraph>
                }
              />
            </List.Item>
          )}
        />
      ) : (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="No results" />
      )}
    </Card>
  );
}
