import os
import pathspec
from openai import OpenAI
from pathlib import Path
from python.FileScanner import markdown_tree



class CampaignEditor:
    MODEL = "gpt-4.1-mini"
    def __init__(self):
        self.chatgpt = OpenAI()

    def _build_ignore_spec(self, ignore_file: Path | None):
        """
        Load .gitignore-style patterns if present.
        Returns a pathspec.PathSpec or None.
        """
        if not ignore_file:
            return None
        p = Path(ignore_file)
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            return pathspec.PathSpec.from_lines("gitwildmatch", lines)
        return None

    def scan_files_with_ignore(self, root_dir: Path, ignore_file: Path | None = None) -> list[Path]:
        """
        Recursively collect files under root_dir, excluding anything matched by
        a .gitignore-style file (if provided).
        """
        root = Path(root_dir).resolve()
        spec = self._build_ignore_spec(ignore_file)

        def is_ignored(p: Path) -> bool:
            if not spec:
                return False
            # PathSpec matches POSIX-style paths; use rel POSIX string
            rel = p.relative_to(root).as_posix()
            # Match files directly; for directories also try with trailing slash
            if spec.match_file(rel):
                return True
            if p.is_dir() and spec.match_file(rel + "/"):
                return True
            return False

        kept: list[Path] = []
        for path in root.rglob("*"):
            # Skip hidden by .gitignore if provided
            # (We don't auto-hide dotfiles; rules should handle that.)
            # Prune ignored directories early
            if path.is_dir():
                if is_ignored(path):
                    # Skip walking into ignored dirs by clearing their children in rglob terms:
                    # rglob can't be pruned directly, so just continue; files inside
                    # will also match ignore when checked.
                    continue
            else:
                if not is_ignored(path):
                    kept.append(path)

        return kept

    def review_and_edit_files(
        self,
        files: list[Path],
        instruction: str,
        explain: bool = False,
        write_mode: str = "suffix",   # "overwrite" | "suffix"
        suffix: str = ".edited"
    ):
        """
        Review/optionally edit each text file against `instruction`.

        Output format contract with the model (strict):
        DECISION: NO_CHANGE — <reason>
        (or)
        DECISION: EDIT — <reason>
        CONTENT_BEGIN
        <full revised file content>
        CONTENT_END

        Returns:
            - edited_paths (list[Path])              # paths written to disk
            - reasons (dict[Path, str]) if explain   # brief rationales
        """
        edited_paths: list[Path] = []
        reasons: dict[Path, str] = {}

        for src in files:
            # Skip binary files
            try:
                original = src.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                print(f"Skipping non-text file: {src}")
                continue

            prompt = (
                "You are an expert editor.\n"
                "Apply the instruction to the file if, and only if, changes are warranted.\n"
                "Output MUST strictly follow one of these formats:\n"
                "1) DECISION: NO_CHANGE — <brief reason>\n"
                "2) DECISION: EDIT — <brief reason>\n"
                "   CONTENT_BEGIN\n"
                "   <full revised file content>\n"
                "   CONTENT_END\n\n"
                "Do not include any other text outside that format.\n\n"
                "INSTRUCTION:\n"
                f"{instruction}\n\n"
                f"FILE PATH: {src}\n\n"
                "----- FILE CONTENT BEGIN -----\n"
                f"{original}\n"
                "----- FILE CONTENT END -----\n"
            )

            resp = self.chatgpt.responses.create(
                model=self.MODEL,
                input=prompt,
                max_output_tokens=4000
            )
            out = (resp.output_text or "").strip()

            # --- Parse decision & optional revised content ---
            decision = None
            reason = ""
            revised = ""

            # First line must start with "DECISION:"
            lines = out.splitlines()
            if not lines or not lines[0].upper().startswith("DECISION:"):
                print(f"Unrecognized output for {src}; skipping.")
                if explain:
                    reasons[src] = "(unrecognized output)"
                continue

            # Extract decision + reason (robust to hyphen/en-dash)
            header = lines[0]
            # Example: "DECISION: EDIT — reason" or "DECISION: NO_CHANGE - reason"
            header_rest = header.split(":", 1)[1].strip()  # "EDIT — reason"
            if header_rest.upper().startswith("NO_CHANGE"):
                decision = "NO_CHANGE"
                parts = header_rest.split("—", 1) if "—" in header_rest else header_rest.split("-", 1)
                if len(parts) > 1:
                    reason = parts[1].strip()
            elif header_rest.upper().startswith("EDIT"):
                decision = "EDIT"
                parts = header_rest.split("—", 1) if "—" in header_rest else header_rest.split("-", 1)
                if len(parts) > 1:
                    reason = parts[1].strip()

                # Find delimited content
                text_str = out  # full response text
                start_tag = "CONTENT_BEGIN"
                end_tag   = "CONTENT_END"
                start_idx = text_str.find(start_tag)
                end_idx   = text_str.rfind(end_tag)
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    revised = text_str[start_idx + len(start_tag):end_idx].lstrip("\n")
                else:
                    # No content found even though decision was EDIT
                    print(f"⚠ EDIT decision but no CONTENT block for: {src}")
                    if explain:
                        reasons[src] = reason or "(no reason)"
                    continue
            else:
                print(f"Unrecognized decision for {src}; skipping.")
                if explain:
                    reasons[src] = "(unrecognized decision)"
                continue

            if explain:
                reasons[src] = reason or "(no rationale provided)"

            # --- Write if edited ---
            if decision == "EDIT" and revised:
                if write_mode == "overwrite":
                    out_path = src
                else:
                    # suffix mode
                    if src.suffix:
                        out_path = src.with_name(src.stem + suffix + src.suffix)
                    else:
                        out_path = src.with_name(src.name + suffix)

                out_path.write_text(revised, encoding="utf-8")
                edited_paths.append(out_path)
                print(f"Edited: {src}  →  {out_path.name}  — {reasons.get(src,'')}")
            else:
                print(f"No change: {src}  — {reasons.get(src,'') if explain else ''}")

        return (edited_paths, reasons) if explain else edited_paths



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

    def process_folder(
        self,
        root_dir: Path,
        ignore_file: Path | None,
        instruction: str,
        explain: bool = False,
        write_mode: str = "suffix",   # "overwrite" | "suffix"
        suffix: str = ".edited"
    ):
        """
        Scan with ignore rules, (optionally) upload everything, ask for edits,
        and write edited files locally (no artifacts required).
        Returns:
            - list[Path] of edited files
            - dict[Path,str] reasons if explain=True
        """
        files = self.scan_files_with_ignore(root_dir, ignore_file)
        print(f"Found {len(files)} files (after ignore).")

        # Upload step is optional for this text-only flow; keep if you want.
        _ = self.upload_files(files)

        if explain:
            edited_paths, reasons = self.review_and_edit_files(
                files, instruction, explain=True, write_mode=write_mode, suffix=suffix
            )
            print("\n--- RATIONALES ---")
            for p, r in reasons.items():
                print(f"{p}: {r}")
            return edited_paths, reasons
        else:
            return self.review_and_edit_files(
                files, instruction, explain=False, write_mode=write_mode, suffix=suffix
            )


    def modify_markdown_text_only(self, src_path: Path, instruction: str, suffix=None) -> Path:
        """
        Read a local Markdown file, ask the model to apply edits, and write
        the result back to the SAME file (or a new one if suffix is given).
        Returns the path written.
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
            max_output_tokens=4000
        )
        revised = resp.output_text

        # If no suffix is provided, overwrite the original file
        if suffix:
            if src_path.suffix:
                out_path = src_path.with_name(src_path.stem + suffix + src_path.suffix)
            else:
                out_path = src_path.with_name(src_path.name + suffix)
        else:
            out_path = src_path  # overwrite original

        out_path.write_text(revised, encoding="utf-8")
        print("Wrote:", out_path)
        return out_path

    def upload_files(self, files: list[Path]) -> dict[Path, str]:
        """
        Upload each file; return {Path: file_id}.
        This is optional for your current text-only edit flow, but kept for future use.
        """
        mapping: dict[Path, str] = {}
        for p in files:
            try:
                with p.open("rb") as f:
                    up = self.chatgpt.files.create(file=f, purpose="assistants")
                mapping[p] = up.id
                print(f"Uploaded: {up.id}  {p}")
            except Exception as e:
                print(f"Upload failed for {p}: {e}")
        return mapping

    def download_file(self, file_id: str, dest_dir: Path) -> Path:
        """
        Download a file artifact returned by the model and save it into dest_dir.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        content = self.chatgpt.files.content(file_id)
        data = content.read() if hasattr(content, "read") else content
        fobj = self.chatgpt.files.retrieve(file_id)
        fname = fobj.filename or (file_id + ".bin")
        out_path = dest_dir / fname
        with open(out_path, "wb") as f:
            f.write(data)
        print("Saved:", out_path)
        return out_path




if __name__ == "__main__":
    editor = CampaignEditor()

    root = Path(r"C:\Development\Timberhearth\characters")
    ignore = Path(r"C:\Development\Timberhearth\campaign_files.ignore")

    instruction = (
        "These files contain the lore for a family-friendly fantasy adventure game. "
        "The players are a seven-year-old boy, Gabriel Thatcher, and his mother, Jessica Willowglen. "
        "Please thoroughly review the files to understand the ongoing storyline so you can act as an expert, "
        "creative, whimsical, and age-appropriate story assistant.\n\n"
        "Then identify which files would benefit from edits or additions to reflect the following changes, "
        "make the appropriate changes, and list which files were modified:\n\n"
        "• Describe an event where Jessica and Gabriel fought a coordinated attack on the village by Vendraxis. "
        "The Creeping Wither pumpkins attacked parts of town; Gabriel and Jessica, along with Gabriel’s dog Poodler, "
        "had to prevent the attack. In the end, the town fountain was destroyed. "
        "Keep tone appropriate for a seven-year-old and maintain continuity with existing lore."
    )

    edited_paths, why = editor.process_folder(
        root, ignore, instruction, explain=True, write_mode="overwrite"
    )


    print("\nSummary of decisions:")
    for path, reason in why.items():
        print(f"- {path.name}: {reason}")


