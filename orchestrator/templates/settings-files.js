const SettingsFiles = (() => {
  const rank = (file) => (file.folder === false ? 2 : file.error ? 0 : 1);

  /**
   * @param files - /api/firewall files: path, folder and error each.
   * @param showMissing - true lists the files whose folder is missing too.
   * @returns {shown, missing}: shown the files to list, those with an error first, then by path, files without their folder
   * last; missing the count of files without their folder.
   */
  function listed(files, showMissing) {
    const shown = files.filter((file) => showMissing || file.folder !== false);
    shown.sort((a, b) => rank(a) - rank(b) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
    return {shown, missing: files.filter((file) => file.folder === false).length};
  }

  return {listed};
})();

if (typeof module === "object" && module.exports) {
  module.exports = SettingsFiles;
}
