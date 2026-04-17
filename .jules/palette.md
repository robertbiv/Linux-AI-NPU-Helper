## 2024-04-17 - Add AccessibleName to PyQt buttons
**Learning:** QToolButton and icon-only QPushButton in PyQt need setAccessibleName to be read properly by screen readers, even when setToolTip is provided. While some screen readers fallback to tooltips, setting accessible name is the standard and most robust way to ensure accessibility for icon-only buttons.
**Action:** Add setAccessibleName to all icon-only buttons in the GUI, mirroring their tooltips, to ensure proper accessibility.
