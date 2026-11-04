/**
 * generationModels.ts — 生成面板与真实生成共用的模型状态。
 *
 * 之前 App.tsx 与 GeneratePanel.tsx 各自拉列表、各自存 selected key：
 * 面板选了本地模型，真正生成仍读另一套状态；本地图像甚至没有合并入口。
 * 这里集中维护「云端 + 本地」列表和选择，避免两套状态再次漂移。
 */
import { create } from "zustand";
import {
  listAudioModels,
  listChatModels,
  listImageModels,
  listMusicModels,
  listVideoModels,
  type AudioModelOption,
  type ImageModelOption,
  type MusicModelOption,
  type VideoModelOption,
} from "./bridge";
import { listLocalImageModels, mergeLocalImageModels } from "./localImage";
import { listLocalVideoModels, mergeLocalVideoModels } from "./localVideo";

export const MODEL_STORAGE_KEYS = {
  image: "shiguang-canvas:model:image",
  video: "shiguang-canvas:model:video",
  compare: "shiguang-canvas:model:compare",
  compareVideo: "shiguang-canvas:model:compare-video",
} as const;

type ModelLists = {
  imageModels: ImageModelOption[];
  videoModels: VideoModelOption[];
  audioModels: AudioModelOption[];
  musicModels: MusicModelOption[];
  chatModelKeys: string[];
};

type SelectionState = {
  selectedModelKey: string;
  selectedVideoModelKey: string;
  selectedAudioModelKey: string;
  selectedMusicModelKey: string;
  compareModelKey: string;
  compareVideoModelKey: string;
};

type Store = ModelLists & SelectionState & {
  setSelectedModelKey: (key: string) => void;
  setSelectedVideoModelKey: (key: string) => void;
  setSelectedAudioModelKey: (key: string) => void;
  setSelectedMusicModelKey: (key: string) => void;
  setCompareModelKey: (key: string) => void;
  setCompareVideoModelKey: (key: string) => void;
};

function readStored(key: string): string {
  try {
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function saveStored(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* storage is optional (private mode / tests) */
  }
}

function validKey(key: string, models: Array<{ channel_id: string; model: string }>): boolean {
  return Boolean(key && models.some((m) => `${m.channel_id}::${m.model}` === key));
}

function chooseKey(
  current: string,
  models: Array<{ channel_id: string; model: string }>,
  preferred: string,
): string {
  if (validKey(current, models)) return current;
  if (validKey(preferred, models)) return preferred;
  const first = models[0];
  return first ? `${first.channel_id}::${first.model}` : "";
}

function chooseCompare(
  current: string,
  models: Array<{ channel_id: string; model: string }>,
  primary: string,
): string {
  if (validKey(current, models) && current !== primary) return current;
  const other = models.find((m) => `${m.channel_id}::${m.model}` !== primary);
  return other ? `${other.channel_id}::${other.model}` : "";
}

export const useGenerationModelStore = create<Store>((set) => ({
  imageModels: [],
  videoModels: [],
  audioModels: [],
  musicModels: [],
  chatModelKeys: [],
  selectedModelKey: readStored(MODEL_STORAGE_KEYS.image),
  selectedVideoModelKey: readStored(MODEL_STORAGE_KEYS.video),
  selectedAudioModelKey: "",
  selectedMusicModelKey: "",
  compareModelKey: readStored(MODEL_STORAGE_KEYS.compare),
  compareVideoModelKey: readStored(MODEL_STORAGE_KEYS.compareVideo),
  setSelectedModelKey: (key) => {
    saveStored(MODEL_STORAGE_KEYS.image, key);
    set({ selectedModelKey: key });
  },
  setSelectedVideoModelKey: (key) => {
    saveStored(MODEL_STORAGE_KEYS.video, key);
    set({ selectedVideoModelKey: key });
  },
  setSelectedAudioModelKey: (key) => set({ selectedAudioModelKey: key }),
  setSelectedMusicModelKey: (key) => set({ selectedMusicModelKey: key }),
  setCompareModelKey: (key) => {
    saveStored(MODEL_STORAGE_KEYS.compare, key);
    set({ compareModelKey: key });
  },
  setCompareVideoModelKey: (key) => {
    saveStored(MODEL_STORAGE_KEYS.compareVideo, key);
    set({ compareVideoModelKey: key });
  },
}));

/** 拉取并合并所有生成模型；调用方只消费返回值做状态提示。 */
export async function refreshGenerationModels(): Promise<{
  warnings: string[];
  activeProviderLabel: string;
  imageCount: number;
  videoCount: number;
}> {
  const [img, vid, aud, mus, chat, localImg, localVid] = await Promise.all([
    listImageModels(),
    listVideoModels(),
    listAudioModels(),
    listMusicModels(),
    listChatModels(),
    listLocalImageModels(),
    listLocalVideoModels(),
  ]);
  const imageModels = mergeLocalImageModels(img.models, localImg);
  const videoModels = mergeLocalVideoModels(vid.models, localVid);
  const current = useGenerationModelStore.getState();
  const selectedModelKey = chooseKey(current.selectedModelKey, imageModels, img.default);
  const selectedVideoModelKey = chooseKey(current.selectedVideoModelKey, videoModels, vid.default);
  const selectedAudioModelKey = chooseKey(current.selectedAudioModelKey, aud.models, aud.default);
  const selectedMusicModelKey = chooseKey(current.selectedMusicModelKey, mus.models, mus.default);
  useGenerationModelStore.setState({
    imageModels,
    videoModels,
    audioModels: aud.models,
    musicModels: mus.models,
    chatModelKeys: (chat.providers || []).flatMap((p) =>
      p.configured ? (p.models || []).map((m) => `${p.id}::${m}`) : [],
    ),
    selectedModelKey,
    selectedVideoModelKey,
    selectedAudioModelKey,
    selectedMusicModelKey,
    compareModelKey: chooseCompare(current.compareModelKey, imageModels, selectedModelKey),
    compareVideoModelKey: chooseCompare(current.compareVideoModelKey, videoModels, selectedVideoModelKey),
  });
  return {
    warnings: [
      ...(img.warnings || []),
      ...(vid.warnings || []),
      ...(aud.warnings || []),
      ...(mus.warnings || []),
    ],
    activeProviderLabel: img.active_provider_label || "",
    imageCount: imageModels.length,
    videoCount: videoModels.length,
  };
}
