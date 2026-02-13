-- Users and Roles for MSSQL

CREATE LOGIN [test_user_1] WITH PASSWORD = 'Test@123';
CREATE USER [test_user_1] FOR LOGIN [test_user_1];
ALTER ROLE db_datareader ADD MEMBER [test_user_1];

CREATE LOGIN [test_user_2] WITH PASSWORD = 'Test@456';
CREATE USER [test_user_2] FOR LOGIN [test_user_2];
ALTER ROLE db_datareader ADD MEMBER [test_user_2];
ALTER ROLE db_datawriter ADD MEMBER [test_user_2];

CREATE LOGIN [test_admin] WITH PASSWORD = 'Admin@789';
CREATE USER [test_admin] FOR LOGIN [test_admin];
ALTER ROLE db_owner ADD MEMBER [test_admin];
