from python.FileScanner import markdown_tree


class CampaignEditor:
    def __init__(self):
        pass

    def make_directory_summary(self):
        pass



if __name__ == "__main__":
    editor = CampaignEditor()

    print(markdown_tree("C:\\Development\\Timberhearth", ignore_file="C:\\Development\\Timberhearth\\campaign_files.ignore", show_hidden=False, max_depth=None))

