import { useEffect, useState } from "react";
import { bridgeToken, promptImageSrc } from "./bridge";

export type PromptCoverImageProps = {
  url: string;
  className?: string;
  alt?: string;
  /** 列表缩略图用 cover；预览用 contain */
  fit?: "cover" | "contain";
  onClick?: () => void;
};

export default function PromptCoverImage({
  url,
  className,
  alt = "",
  fit = "cover",
  onClick,
}: PromptCoverImageProps) {
  const [src, setSrc] = useState("");
  const [broken, setBroken] = useState(false);

  useEffect(() => {
    if (!url) {
      setSrc("");
      setBroken(false);
      return;
    }
    setBroken(false);
    setSrc(bridgeToken() ? promptImageSrc(url) : url);
  }, [url]);

  if (!url) return null;

  if (broken) {
    return (
      <div
        className={`${className || ""} placeholder`.trim()}
        title="参考图加载失败（外链受限或已失效）"
        onClick={onClick}
      >
        🖼
      </div>
    );
  }
  return (
    <img
      className={className}
      src={src}
      alt={alt}
      loading="lazy"
      draggable={false}
      style={fit === "contain" ? { objectFit: "contain" } : undefined}
      onClick={onClick}
      onError={() => {
        if (src === url && bridgeToken()) {
          setSrc(promptImageSrc(url));
          return;
        }
        setBroken(true);
      }}
    />
  );
}
