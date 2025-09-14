import os
from openai import OpenAI
from pathlib import Path
from python.FileScanner import markdown_tree



class CampaignEditor:
    MODEL = "gpt-4.1-mini"
    def __init__(self):
        self.chatgpt = OpenAI()

    def make_directory_summary(self):
        pass

    def chat(self, prompt: str) -> str:
        resp = self.chatgpt.responses.create(
            model=self.MODEL,
            input=prompt
        )
        return resp.output_text
    
    def upload_file(self, path: Path) -> str:
        with path.open("rb") as f:
            up = self.chatgpt.files.create(file=f, purpose="assistants")
        print("Uploaded:", up.id, path.name)
        return up.id
    
    def summarize_markdown(self, path: Path):
        text = path.read_text(encoding="utf-8")
        resp = self.chatgpt.responses.create(
            model=self.MODEL,
            input=f"Here is a markdown file:\n\n{text}\n\nPlease summarize in 5 bullets."
        )
        print(resp.output_text)

    def request_modification(self, file_id: str, instruction: str) -> str:
        resp = self.chatgpt.responses.create(
            model=self.MODEL,
            # Enable the code sandbox so the model can read & write files
            tools=[{"type": "code_interpreter"}],

            # ✅ Grant the sandbox access to your uploaded file
            attachments=[{
                "file_id": file_id,
                "tools": [{"type": "code_interpreter"}]
            }],

            # Ask explicitly for a new file artifact to be created
            input=[{
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Open the attached file in the code sandbox. "
                        f"Apply these edits:\n{instruction}\n\n"
                        "Then WRITE a new file and include it as a file output. "
                        "Name the new file by appending '.edited' before the extension "
                        "(e.g., bryna_willowglen.edited.md)."
                    )
                }]
            }],
            max_output_tokens=500
        )

        # Find the produced file artifact (robust scan)
        modified_file_id = None
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) == "output_file":
                modified_file_id = item.file_id
                break

        if not modified_file_id:
            # Fallback recursive crawl for SDK shape diffs
            def walk(obj):
                if isinstance(obj, dict):
                    if obj.get("type") == "output_file" and "file_id" in obj:
                        return obj["file_id"]
                    for v in obj.values():
                        fid = walk(v)
                        if fid: return fid
                elif isinstance(obj, list):
                    for v in obj:
                        fid = walk(v)
                        if fid: return fid
                return None
            modified_file_id = walk(resp.__dict__)

        if not modified_file_id:
            raise RuntimeError(
                "No output file was returned. Try making the instruction explicit: "
                "'write a new file and include it as a file output.'"
            )

        print("Model produced modified file:", modified_file_id)
        return modified_file_id

    def modify_markdown_text_only(self, src_path: Path, instruction: str, suffix=".edited") -> Path:
        """
        Read a local Markdown file, ask the model to apply edits, and write a new file.
        Returns the path to the new file.
        """
        original = src_path.read_text(encoding="utf-8")

        prompt = (
            "You are an expert editor. Apply the following edits to the Markdown text.\n"
            "Keep all existing front matter, headings, and formatting unless the edit requires changes.\n"
            "Return ONLY the complete revised Markdown, nothing else.\n\n"
            f"Edits:\n{instruction}\n\n"
            "Markdown begins below:\n"
            "-----\n"
            f"{original}\n"
            "-----\n"
        )

        resp = self.chatgpt.responses.create(
            model=self.MODEL,
            input=prompt,
            max_output_tokens=4000  # adjust as needed
        )
        revised = resp.output_text

        # write alongside the source, e.g. bryna_willowglen.edited.md
        if src_path.suffix:
            out_path = src_path.with_name(src_path.stem + suffix + src_path.suffix)
        else:
            out_path = src_path.with_name(src_path.name + suffix)

        out_path.write_text(revised, encoding="utf-8")
        print("Wrote:", out_path)
        return out_path



if __name__ == "__main__":
    editor = CampaignEditor()

    src = Path(r"C:\Development\Timberhearth\characters\bryna_willowglen\bryna_willowglen.md")
    file_id = editor.upload_file(src)

    editor.modify_markdown_text_only(
        src_path=src,
        instruction="Add to the notable events section: Bryna was once chased by a living pumpkin."
    )

