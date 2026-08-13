-- PixelForge Bridge for Aseprite
-- Import a ComfyUI-PixelForge-H3 sprite run (frames.json manifest + PNG sequence)
-- as a native .aseprite document with frame durations and a tag.
--
-- Install: copy this folder into Aseprite's extensions directory
--   (File > Scripts > Open Scripts Folder, then go up one level into "extensions"),
-- or zip it, rename to .aseprite-extension, and add via Edit > Preferences > Extensions.
-- Usage: Sprite menu (or File) > "Import PixelForge Run..." -> pick frames.json

local function read_file(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  return s
end

-- minimal JSON reader for the flat manifest PixelForge writes
local function parse_manifest(text)
  local tag = text:match('"tag"%s*:%s*"([^"]*)"') or "run"
  local fps = tonumber(text:match('"fps"%s*:%s*([%d%.]+)')) or 12
  local fw = tonumber(text:match('"frame_size"%s*:%s*%[%s*(%d+)'))
  local fh = tonumber(text:match('"frame_size"%s*:%s*%[%s*%d+%s*,%s*(%d+)'))
  local frames = {}
  for file, dur in text:gmatch('"file"%s*:%s*"([^"]*)"%s*,%s*"duration_ms"%s*:%s*(%d+)') do
    table.insert(frames, { file = file, duration_ms = tonumber(dur) })
  end
  return { tag = tag, fps = fps, w = fw, h = fh, frames = frames }
end

local function import_run()
  local dlg = Dialog("Import PixelForge Run")
  dlg:file{ id = "manifest", label = "frames.json", open = true,
            filetypes = { "json" }, focus = true }
  dlg:entry{ id = "tag", label = "Tag name", text = "run" }
  dlg:button{ id = "ok", text = "Import" }
  dlg:button{ id = "cancel", text = "Cancel" }
  dlg:show()
  local data = dlg.data
  if not data.ok or not data.manifest or data.manifest == "" then return end

  local text = read_file(data.manifest)
  if not text then
    app.alert("Could not read: " .. data.manifest)
    return
  end
  local m = parse_manifest(text)
  if #m.frames == 0 or not m.w or not m.h then
    app.alert("No frames found in manifest.")
    return
  end
  local dir = data.manifest:match("^(.*)[/\\][^/\\]*$") or "."

  local spr = Sprite(m.w, m.h, ColorMode.RGBA)
  for i = 2, #m.frames do spr:newEmptyFrame() end
  for i, fr in ipairs(m.frames) do
    local img = Image{ fromFile = dir .. "/" .. fr.file }
    spr:newCel(spr.layers[1], i, img, Point(0, 0))
    spr.frames[i].duration = (fr.duration_ms or 100) / 1000.0
  end
  local t = spr:newTag(1, #m.frames)
  t.name = (data.tag ~= "" and data.tag) or m.tag
  app.refresh()
  app.alert("Imported " .. #m.frames .. " frames (" .. m.w .. "x" .. m.h .. ").")
end

function init(plugin)
  plugin:newCommand{
    id = "PixelForgeImportRun",
    title = "Import PixelForge Run...",
    group = "file_import",
    onclick = import_run,
  }
end

function exit(plugin) end
