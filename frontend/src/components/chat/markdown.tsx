"use client";

import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  renderWithMentions,
  type MentionsContext,
} from "@/lib/render-with-mentions";

function withMentions(node: ReactNode, ctx: MentionsContext): ReactNode {
  if (node == null || typeof node === "boolean") return node;
  if (typeof node === "string") return renderWithMentions(node, ctx);
  if (Array.isArray(node)) {
    return node.map((child, i) => (
      <Fragment key={i}>{withMentions(child, ctx)}</Fragment>
    ));
  }
  return node;
}

export function ChatMarkdown({
  content,
  mentionsContext,
}: {
  content: string;
  mentionsContext?: MentionsContext;
}) {
  const ctx = mentionsContext;
  const components = ctx
    ? {
        p: ({ children }: { children?: ReactNode }) => (
          <p>{withMentions(children, ctx)}</p>
        ),
        li: ({ children }: { children?: ReactNode }) => (
          <li>{withMentions(children, ctx)}</li>
        ),
        strong: ({ children }: { children?: ReactNode }) => (
          <strong>{withMentions(children, ctx)}</strong>
        ),
        em: ({ children }: { children?: ReactNode }) => (
          <em>{withMentions(children, ctx)}</em>
        ),
        td: ({ children }: { children?: ReactNode }) => (
          <td>{withMentions(children, ctx)}</td>
        ),
        th: ({ children }: { children?: ReactNode }) => (
          <th>{withMentions(children, ctx)}</th>
        ),
      }
    : undefined;

  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
