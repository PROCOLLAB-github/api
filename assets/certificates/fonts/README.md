# Certificate fonts

The renderer bundles these Google Fonts files at commit
[`e7db6ca603fd4862010383ff17ffd6cc4ffac1c0`](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0):

| Local file | Upstream file | SHA-256 |
| --- | --- | --- |
| PTSerif-Regular.ttf | ofl/ptserif/PT_Serif-Web-Regular.ttf | a4951fade06ff8f09b7673aa81ffb65a8cd409e24d3289a6dc670bc4dda2557a |
| PTSerif-Bold.ttf | ofl/ptserif/PT_Serif-Web-Bold.ttf | 038ba7336bd7ea14f12ad155bed51a4345cac5153275d521dec3ba04021c526e |
| Lobster-Regular.ttf | ofl/lobster/Lobster-Regular.ttf | d6568e697fd50cedc0be04d8aae4127fe95add607e7bff954ca88604be80c205 |

PT Serif: ParaType. See [license and attribution](PTSerif-OFL.txt).
Lobster: The Lobster Project Authors. See [license and attribution](Lobster-OFL.txt).
The upstream font names and outlines are unchanged. Mont continues to use the
existing application assets in `assets/users/user_CV/`.

Frontend WOFF2 files are lossless container conversions of these TTF sources.
The backend uses the exact TTF files for both Pillow measurements and embedded PDF
faces. The renderer never downloads fonts during PDF generation. Lobster has one
400-weight face; it is used without synthetic bold. PT Serif uses 400/700 and Mont
uses the existing 400/600 faces.
