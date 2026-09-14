export const ROLES = new Set(('generic document text lineBreak paragraph heading link button textField checkbox radio switch comboBox listBox option group form list listItem table row cell rowHeader columnHeader definitionList term definition image figure caption code math dialog alert status navigation main banner contentInfo complementary search tab tabList tabPanel separator slider spinButton progress tree treeItem grid gridCell menu menuItem frame unknown').split(' '));
export const RELATIONS = new Set(('labelledBy describedBy errorMessage details controls owns activeDescendant headers labelFor formOwner choices fragmentTarget captionedBy embeds').split(' '));
export const ACTIONS = new Set(('invoke focus setValue select toggle expand collapse increment decrement scroll scrollIntoView').split(' '));
export const BOOLEAN_STATES = new Set(('disabled readOnly required focusable selected expanded busy modal multiSelectable').split(' '));
export const COVERAGE = new Set(['complete', 'partial', 'unknown']);
export const PROFILE = new Set(['structure', 'excerpt', 'budget']);
export const NODE_KEYS = new Set(('role children text name description value states actions destination labelHints language direction structure exposure bounds coverage').split(' '));
export const GAP_FIELDS = new Set(['text', 'children', 'relation', 'media', 'upstream']);
