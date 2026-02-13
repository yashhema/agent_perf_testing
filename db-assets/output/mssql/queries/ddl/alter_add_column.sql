-- Add column if not exists
IF NOT EXISTS (SELECT * FROM sys.columns
               WHERE object_id = OBJECT_ID(?) AND name = ?)
    EXEC('ALTER TABLE ' + ? + ' ADD ' + ? + ' ' + ?)