import unittest

from property_watcher.image_archive import classify_image, extract_image_candidates


class ImageArchiveTest(unittest.TestCase):
    def test_classifies_only_indoor_images(self):
        self.assertEqual(classify_image("リビング"), "indoor")
        self.assertEqual(classify_image("洗面台・洗面所"), "indoor")
        self.assertIsNone(classify_image("現地外観写真"))
        self.assertIsNone(classify_image("間取り図"))

    def test_extracts_lazy_suumo_image_and_requests_larger_size(self):
        html = """
        <html><body>
          <img alt="リビング" class="js-scrollLazy-image"
               rel="https://img01.suumo.com/jj/resizeImage?src=photo%2Fliving.jpg&amp;w=220&amp;h=165">
          <img alt="現地外観写真"
               rel="https://img01.suumo.com/jj/resizeImage?src=photo%2Foutside.jpg&amp;w=220&amp;h=165">
          <img alt="リビング"
               rel="https://img01.suumo.com/jj/resizeImage?src=photo%2Fliving.jpg&amp;w=96&amp;h=72">
        </body></html>
        """
        images = extract_image_candidates(html, "https://suumo.jp/property")
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].caption, "リビング")
        self.assertIn("w=1280", images[0].download_url)
        self.assertIn("h=1280", images[0].download_url)


if __name__ == "__main__":
    unittest.main()
